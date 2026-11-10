
import { SocketClient } from '@open-wa/socket-client';

const client = await SocketClient.connect(
  'http://127.0.0.1:8080'
);

// Restrict testing to one approved sender.
const ALLOWED_SENDER = '274250992713866@lid';

// Track processed messages to avoid duplicate replies.
const processed = new Set();

console.log('Connected to OpenWA.');
console.log('Waiting for voice notes...');

await client.listen('onMessage', async (payload) => {
  // Remote events may wrap the message inside payload.message.
  const message = payload?.message ?? payload;

  if (!message?.id) return;
  if (message.fromMe === true) return;

  // Process audio only.
  if (!message.mimetype?.startsWith('audio/')) return;

  // Ignore messages from anyone except your test phone.
  if (message.from !== ALLOWED_SENDER) return;

  if (processed.has(message.id)) return;
  processed.add(message.id);

  console.log(
    `Voice note received (${message.duration ?? '?'} seconds).`
  );

  try {
    // Download and decrypt the original audio.
    // Fetch the complete message from OpenWA.
	const fullMessage = await client.getMessageById(message.id);

	if (!fullMessage || typeof fullMessage !== 'object') {
  	throw new Error('Could not retrieve the complete message.');
	}

	// Decrypt the complete message.
	const audioDataUrl = await client.ask('decryptMedia', {
  	message: fullMessage,
	});

    if (
      typeof audioDataUrl !== 'string' ||
      !audioDataUrl.startsWith('data:audio/')
    ) {
      throw new Error('Unexpected decrypted audio format.');
    }

    console.log('Audio decrypted. Sending it back...');

    // Send the original recording as a WhatsApp voice note.
    const result = await client.sendPtt(
      message.from,
      audioDataUrl
    );

    console.log('Voice echo send result:', Boolean(result));
  } catch (error) {
    console.error(
      'Voice echo failed:',
      error?.message ?? String(error)
    );

    processed.delete(message.id);
  }
});

console.log('Voice-note listener registered.');

process.once('SIGINT', () => {
  client.close();
  process.exit(0);
});
