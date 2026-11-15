# Conversation Memory & Privacy Architecture

KrishiVaani is designed with privacy-first engineering, ensuring smallholder farmers retain complete control over their personal information and conversation history in compliance with the Digital Personal Data Protection (DPDP) Act.

---

## 1. Pseudonymous HMAC User Hashing

Raw Telegram user IDs (e.g., `123456789`) are never persisted in plain text. All conversation records and preferences in [`ConversationMemoryStore`](../app/telegram/memory.py) are keyed by a cryptographic hash:

$$\text{user\_hash} = \text{HMAC-SHA256}(\text{USER\_ID\_HASH\_SALT}, \text{telegram\_user\_id})$$

- If `USER_ID_HASH_SALT` is missing, the memory store raises a runtime error rather than operating insecurely.
- Even with direct read access to the SQLite database, stored records cannot be linked back to Telegram accounts without the private salt.

---

## 2. Conversation Memory Lifecyle

The memory layer retains the **last 4 conversation turns** in the SQLite `chat_turns` table to enable conversational continuity (e.g., resolving follow-up questions such as *"How much water does it need?"* after discussing cotton):

| Field | Description |
| :--- | :--- |
| `user_hash` | Pseudonymous HMAC identifier. |
| `question_text` / `answer_text` | Text transcript of query and validated response (truncated to 400 chars). |
| `intent` | Classified intent (e.g., `crop_management`, `weather_inquiry`). |
| `profile_district` / `profile_mandal` | Extracted geographic location details. |
| `profile_crops` / `profile_soil` | Mentioned crop, soil, and water source parameters. |

> [!IMPORTANT]
> Stored conversation turns are provided to the LLM solely as background context for resolving conversational pronouns or follow-up topics. The orchestrator explicitly instructs the model **never to treat past conversational turns as verified agricultural evidence**.

---

## 3. Right to Erasure (`/forget` Command)

Farmers can permanently erase all stored records at any time by sending `/forget` on Telegram:

1. The bot computes the user's `user_hash`.
2. It executes an atomic SQL deletion:
   ```sql
   DELETE FROM chat_turns WHERE user_hash = ?;
   DELETE FROM telegram_user_preferences WHERE user_hash = ?;
   ```
3. The bot clears active session cache and acknowledges erasure to the farmer in their preferred language.

---

## 4. Location Sharing & Consent Architecture

- **In-Memory Location**: Real-time GPS location pins shared on Telegram are cached in an ephemeral in-memory session with a 30-minute time-to-live (TTL).
- **Third-Party Weather Consent**: Under the DPDP framework, receiving a location pin does **not** grant automatic consent to share coordinates with third-party weather APIs. The bot explicitly presents an inline consent notice before calling WeatherAPI, and logs affirmative consent events with timestamp and disclosure version.

