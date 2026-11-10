"""
Temporary diagnostic script for investigating Twilio WhatsApp outbound error 21654.

Security rules:
- Reads credentials from existing Settings.
- NEVER prints credentials, auth tokens, phone numbers, or message content.
- Logs ONLY outgoing form-field names (keys), HTTP method, URL, and response status/error code.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3
from typing import Optional, Dict, Any, List
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.core.config import settings
from app.twilio.client import TwilioClient
from app.twilio.security import mask_phone_number


def get_latest_recipient_from_db() -> Optional[str]:
    """Get the latest incoming sender from twilio_events database without printing it."""
    db_path = settings.DATABASE_PATH
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("SELECT from_number, to_number FROM twilio_events ORDER BY rowid DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row:
            return row[0], row[1]
    except Exception as e:
        print(f"[DIAGNOSTIC] Could not read recipient from DB: {type(e).__name__}")
    return None, None


class TransportSpy:
    """Interception wrapper to inspect exact form-data field names at the HTTP transport boundary."""

    def __init__(self, original_http_client):
        self.original_http_client = original_http_client
        self.last_method = None
        self.last_url = None
        self.last_field_names: List[str] = []
        self.last_has_content_variables = False
        self.last_has_content_sid = False

    def request(self, method, url, params=None, data=None, headers=None, auth=None, timeout=None, allow_redirects=False):
        self.last_method = method
        self.last_url = url
        if isinstance(data, dict):
            self.last_field_names = list(data.keys())
            self.last_has_content_variables = "ContentVariables" in data
            self.last_has_content_sid = "ContentSid" in data
        return self.original_http_client.request(
            method, url, params=params, data=data, headers=headers, auth=auth, timeout=timeout, allow_redirects=allow_redirects
        )


def run_diagnostics():
    print("=" * 60)
    print("TWILIO OUTBOUND ERROR 21654 DIAGNOSTIC SUITE")
    print("=" * 60)

    # 1. Environment & Configuration Check
    print("\n--- 1. Configuration Audit ---")
    account_sid_present = bool(settings.twilio_account_sid)
    auth_token_present = bool(settings.twilio_auth_token)
    whatsapp_from_present = bool(settings.twilio_whatsapp_from)
    content_sid_present = bool(settings.twilio_content_sid)

    print(f"TWILIO_ACCOUNT_SID configured: {account_sid_present}")
    print(f"TWILIO_AUTH_TOKEN configured: {auth_token_present}")
    print(f"TWILIO_WHATSAPP_FROM configured: {whatsapp_from_present}")
    print(f"TWILIO_CONTENT_SID configured: {content_sid_present}")
    print(f"From number (masked): {mask_phone_number(settings.twilio_whatsapp_from)}")

    if not account_sid_present or not auth_token_present:
        print("[ERROR] Twilio credentials missing in settings.")
        return

    recipient_from_event, destination_from_event = get_latest_recipient_from_db()
    if not recipient_from_event:
        print("[ERROR] No incoming message found in twilio_events to test reply against.")
        return

    print(f"Recipient from latest webhook (masked): {mask_phone_number(recipient_from_event)}")
    print(f"Destination number from latest webhook (masked): {mask_phone_number(destination_from_event)}")

    # 2. Inspect SDK Transport Serialization (Direct Twilio SDK)
    print("\n--- 2. Inspect SDK Transport Boundary (Direct messages.create) ---")
    raw_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    spy = TransportSpy(raw_client.http_client)
    raw_client.http_client = spy

    test_body = "కృషివాణి పరీక్షా సందేశం (KrishiVaani Diagnostic Test)"
    direct_send_success = False
    direct_send_sid = None
    direct_send_error = None

    try:
        msg = raw_client.messages.create(
            body=test_body,
            from_=settings.twilio_whatsapp_from,
            to=recipient_from_event,
        )
        direct_send_success = True
        direct_send_sid = msg.sid
    except TwilioRestException as tre:
        direct_send_error = f"TwilioRestException code={tre.code}, status={tre.status}, msg={tre.msg}"
    except Exception as ex:
        direct_send_error = f"Exception: {type(ex).__name__}: {str(ex)}"

    print("HTTP Request Details:")
    print(f"  HTTP Method: {spy.last_method}")
    print(f"  Field Names Sent in HTTP Data: {spy.last_field_names}")
    print(f"  Is 'ContentVariables' in form fields: {spy.last_has_content_variables}")
    print(f"  Is 'ContentSid' in form fields: {spy.last_has_content_variables}")
    print(f"  Direct SDK Call Result: {'SUCCESS' if direct_send_success else 'FAILED'}")
    if direct_send_success:
        print(f"  Message SID: {direct_send_sid}")
    else:
        print(f"  Error: {direct_send_error}")

    # 3. Application's normal send_text_message
    print("\n--- 3. Application TwilioClient.send_text_message Test ---")
    app_client = TwilioClient(content_sid=None)
    app_spy = TransportSpy(app_client.rest_client.http_client)
    app_client.rest_client.http_client = app_spy

    app_send_success = False
    app_send_sid = None
    app_send_error = None

    try:
        sid = app_client.send_text_message(
            to=recipient_from_event,
            text=test_body,
        )
        app_send_success = True
        app_send_sid = sid
    except Exception as ex:
        app_send_error = f"{type(ex).__name__}: {str(ex)}"

    print("HTTP Request Details (App TwilioClient):")
    print(f"  Field Names Sent in HTTP Data: {app_spy.last_field_names}")
    print(f"  Is 'ContentVariables' in form fields: {app_spy.last_has_content_variables}")
    print(f"  App Client Call Result: {'SUCCESS' if app_send_success else 'FAILED'}")
    if app_send_success:
        print(f"  Message SID: {app_send_sid}")
    else:
        print(f"  Error: {app_send_error}")

    # 4. If destination_from_event differed from settings.twilio_whatsapp_from, test that as from_
    if destination_from_event and destination_from_event != settings.twilio_whatsapp_from:
        print("\n--- 4. Cross-Sender Comparison Test (using webhook destination as sender) ---")
        print(f"  Testing from_={mask_phone_number(destination_from_event)}")
        cross_spy = TransportSpy(raw_client.http_client)
        raw_client.http_client = cross_spy
        cross_success = False
        cross_sid = None
        cross_error = None
        try:
            msg = raw_client.messages.create(
                body=test_body,
                from_=destination_from_event,
                to=recipient_from_event,
            )
            cross_success = True
            cross_sid = msg.sid
        except TwilioRestException as tre:
            cross_error = f"TwilioRestException code={tre.code}, status={tre.status}, msg={tre.msg}"
        except Exception as ex:
            cross_error = f"Exception: {type(ex).__name__}: {str(ex)}"

        print(f"  Field Names: {cross_spy.last_field_names}")
        print(f"  Cross Sender Call Result: {'SUCCESS' if cross_success else 'FAILED'}")
        if cross_success:
            print(f"  Message SID: {cross_sid}")
        else:
            print(f"  Error: {cross_error}")

    print("\n" + "=" * 60)
    print("DIAGNOSTICS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_diagnostics()
