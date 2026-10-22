const http = require("http");

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
} = require("@whiskeysockets/baileys");

const PORT = 23841;
const HOST = "127.0.0.1";
const AUTH_DIR = "./auth";
const MESSAGE_STORE = "./data/incoming_messages.json";

let sock = null;
let connectionState = "starting";
let lastError = null;

function loadIncomingMessages() {
  try {
    const fs = require("fs");
    if (!fs.existsSync(MESSAGE_STORE)) return [];
    const data = JSON.parse(fs.readFileSync(MESSAGE_STORE, "utf8"));
    return Array.isArray(data) ? data : [];
  } catch (error) {
    console.error("[WHATSAPP] Failed to load message store:", error);
    return [];
  }
}

function saveIncomingMessages(messages) {
  const fs = require("fs");
  const path = require("path");

  fs.mkdirSync(path.dirname(MESSAGE_STORE), {
    recursive: true,
  });

  fs.writeFileSync(
    MESSAGE_STORE,
    JSON.stringify(messages, null, 2),
    "utf8"
  );
}

function isDirectJid(jid) {
  const value = String(jid || "");
  return value.endsWith("@s.whatsapp.net") || value.endsWith("@lid");
}

function extractMessageText(message) {
  if (!message) return "";

  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentMessage?.caption ||
    ""
  ).trim();
}

function storeIncomingMessage(message, { historical = false } = {}) {
  const key = message?.key || {};
  const messageId = key.id;

  if (!messageId) return;

  const chatJid = key.remoteJid || "";

  // Ignore WhatsApp Status/Broadcast messages.
  if (chatJid === "status@broadcast") return;

  // DM-only: groups, newsletters and broadcasts are never stored.
  if (!isDirectJid(chatJid)) return;

  const text = extractMessageText(message.message);

  if (!text) return;

  const messages = loadIncomingMessages();

  if (messages.some(item => item.id === messageId)) {
    return;
  }

  const entry = {
    id: messageId,
    chatJid: key.remoteJid || null,
    senderJid: key.participant || key.remoteJid || null,
    // Phone-number JID when WhatsApp addresses the chat by @lid (if provided).
    altJid: key.remoteJidAlt || key.senderPn || null,
    fromMe: Boolean(key.fromMe),
    pushName: message.pushName || null,
    text,
    timestamp: Number(message.messageTimestamp || Math.floor(Date.now() / 1000)),
    receivedAt: Date.now(),
    // Own messages and old synced history are kept as chat context only;
    // they must never trigger an auto-reply.
    processed: Boolean(key.fromMe) || historical,
  };

  messages.push(entry);

  // Keep the local queue bounded.
  const trimmed = messages.slice(-3000);

  saveIncomingMessages(trimmed);

  console.log(
    `[WHATSAPP] Incoming message stored: ${entry.pushName || entry.senderJid || entry.chatJid}`
  );
}

// ---------------------------------------------------------------------------
// First-time linking. `python setup.py` sets JARVIS_WHATSAPP_PAIR_NUMBER so the
// account can be linked with an 8-character code (works on a single phone,
// where you cannot scan your own screen). Without it a QR code is printed.
// ---------------------------------------------------------------------------
const PAIR_NUMBER = String(
  process.env.JARVIS_WHATSAPP_PAIR_NUMBER || ""
).replace(/\D/g, "");
let pairingRequestedAt = 0;

let qrTerminal = null;
try {
  qrTerminal = require("qrcode-terminal");
} catch (_) {
  qrTerminal = null;
}

async function handleUnlinked(qr) {
  if (sock?.authState?.creds?.registered) return;

  if (PAIR_NUMBER) {
    // A code stays valid for a couple of minutes; ask for a fresh one after that.
    if (Date.now() - pairingRequestedAt < 100000) return;
    pairingRequestedAt = Date.now();

    try {
      const code = await sock.requestPairingCode(PAIR_NUMBER);
      const pretty = String(code).match(/.{1,4}/g)?.join("-") || code;
      console.log(`[WHATSAPP] PAIRING CODE: ${pretty}`);
      console.log(
        "[WHATSAPP] On your phone: WhatsApp > Settings > Linked devices > " +
          "Link a device > 'Link with phone number instead', then enter the code."
      );
    } catch (error) {
      pairingRequestedAt = 0;
      console.error("[WHATSAPP] Could not request a pairing code:", error?.message || error);
    }
    return;
  }

  if (qrTerminal) {
    console.log("[WHATSAPP] Scan this QR: WhatsApp > Linked devices > Link a device");
    qrTerminal.generate(qr, { small: true });
  } else {
    console.log("[WHATSAPP] Not linked, and qrcode-terminal is missing (run npm ci).");
  }
}

async function connectWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  sock = makeWASocket({
    auth: state,
    markOnlineOnConnect: false,
    printQRInTerminal: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("messages.upsert", ({ messages, type }) => {
    for (const message of messages || []) {
      try {
        // "notify" = live message; anything else is offline catch-up/history.
        storeIncomingMessage(message, { historical: type !== "notify" });
      } catch (error) {
        console.error(
          "[WHATSAPP] Failed to store incoming message:",
          error
        );
      }
    }
  });

  sock.ev.on("messaging-history.set", (data) => {
    try {
      const messages = data?.messages || [];

      console.log(
        `[WHATSAPP] History sync: ${messages.length} messages`
      );

      for (const message of messages) {
        storeIncomingMessage(message, { historical: true });
      }
    } catch (error) {
      console.error(
        "[WHATSAPP] Failed to process history sync:",
        error
      );
    }
  });

  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      await handleUnlinked(qr);
    }

    if (connection === "connecting") {
      connectionState = "connecting";
      console.log("[WHATSAPP] Connecting...");
    }

    if (connection === "open") {
      connectionState = "open";
      lastError = null;
      console.log("[WHATSAPP] Connected.");
    }

    if (connection === "close") {
      connectionState = "closed";

      const statusCode =
        lastDisconnect?.error?.output?.statusCode;

      if (statusCode === DisconnectReason.loggedOut) {
        lastError = "WhatsApp session is logged out.";
        console.error("[WHATSAPP] Logged out. Auth was not deleted.");
        return;
      }

      console.log("[WHATSAPP] Connection closed; reconnecting...");
      setTimeout(connectWhatsApp, 3000);
    }
  });
}


function normalizeGroupName(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

async function resolveWhatsAppGroup(name) {
  if (!sock || connectionState !== "open") {
    throw new Error("WhatsApp is not connected.");
  }

  const target = normalizeGroupName(name);

  if (!target) {
    throw new Error("Group name is required.");
  }

  const groups = await sock.groupFetchAllParticipating();

  const matches = Object.entries(groups || {}).filter(([, group]) => {
    return normalizeGroupName(group?.subject) === target;
  });

  if (matches.length === 1) {
    const [jid, group] = matches[0];

    return {
      jid,
      subject: group?.subject || name,
    };
  }

  if (matches.length > 1) {
    throw new Error(`Multiple WhatsApp groups match "${name}".`);
  }

  throw new Error(`WhatsApp group "${name}" was not found.`);
}

function sendJson(res, statusCode, data) {
  const body = JSON.stringify(data);

  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });

  res.end(body);
}

function readBody(req, maxBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    let body = "";

    req.on("data", chunk => {
      body += chunk;

      if (body.length > maxBytes) {
        reject(new Error("Request body too large."));
        req.destroy();
      }
    });

    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/status") {
      return sendJson(res, 200, {
        ok: true,
        connected: connectionState === "open",
        state: connectionState,
        lastError,
        port: PORT,
      });
    }

    if (req.method === "GET" && req.url.startsWith("/messages")) {
      if (!sock || connectionState !== "open") {
        return sendJson(res, 503, {
          ok: false,
          error: "WhatsApp is not connected.",
        });
      }

      const parsed = new URL(req.url, `http://${HOST}:${PORT}`);
      const limitRaw = Number(parsed.searchParams.get("limit") || 50);
      const limit = Math.max(1, Math.min(limitRaw || 50, 200));

      const messages = loadIncomingMessages()
        .filter(item => !item.processed)
        .filter(item => !item.fromMe)
        .filter(item => isDirectJid(item.chatJid))
        .slice(0, limit);

      return sendJson(res, 200, {
        ok: true,
        messages,
        count: messages.length,
      });
    }

    if (req.method === "GET" && req.url.startsWith("/history")) {
      const parsed = new URL(req.url, `http://${HOST}:${PORT}`);
      const chat = String(parsed.searchParams.get("chat") || "");
      const limitRaw = Number(parsed.searchParams.get("limit") || 12);
      const limit = Math.max(1, Math.min(limitRaw || 12, 50));

      // `chat` may be a JID or a bare phone number; `name` is a fallback that
      // matches the contact's WhatsApp display name (needed for @lid chats).
      const name = String(parsed.searchParams.get("name") || "").trim().toLowerCase();
      const digitsOf = value => String(value || "").split("@")[0].replace(/\D/g, "");
      const wanted = digitsOf(chat);

      if (chat.includes("@") && !isDirectJid(chat)) {
        return sendJson(res, 400, {
          ok: false,
          error: "History is only available for direct chats.",
        });
      }

      if (!chat && !name) {
        return sendJson(res, 400, {
          ok: false,
          error: "Provide a chat or a contact name.",
        });
      }

      const allMessages = loadIncomingMessages();

      let rows = chat
        ? allMessages.filter(item =>
            item.chatJid === chat ||
            (wanted &&
              (digitsOf(item.chatJid) === wanted || digitsOf(item.altJid) === wanted))
          )
        : [];

      if (!rows.length && name) {
        const chats = new Set(
          allMessages
            .filter(item =>
              !item.fromMe &&
              isDirectJid(item.chatJid) &&
              String(item.pushName || "").toLowerCase().includes(name)
            )
            .map(item => item.chatJid)
        );
        rows = allMessages.filter(item => chats.has(item.chatJid));
      }

      const messages = rows
        .sort((a, b) => a.timestamp - b.timestamp)
        .slice(-limit)
        .map(item => ({
          id: item.id,
          fromMe: item.fromMe,
          pushName: item.pushName,
          text: item.text,
          timestamp: item.timestamp,
        }));

      return sendJson(res, 200, { ok: true, messages, count: messages.length });
    }

    if (req.method === "POST" && req.url === "/messages/ack") {
      const raw = await readBody(req);
      const data = JSON.parse(raw || "{}");

      const ids = Array.isArray(data.ids)
        ? data.ids.map(String)
        : [];

      if (!ids.length) {
        return sendJson(res, 400, {
          ok: false,
          error: "Message IDs are required.",
        });
      }

      const idSet = new Set(ids);
      const messages = loadIncomingMessages();

      let acknowledged = 0;

      for (const message of messages) {
        if (idSet.has(String(message.id))) {
          if (!message.processed) {
            message.processed = true;
            message.processedAt = Date.now();
            acknowledged += 1;
          }
        }
      }

      saveIncomingMessages(messages);

      return sendJson(res, 200, {
        ok: true,
        acknowledged,
      });
    }

    if (req.method === "POST" && req.url === "/resolve-group") {
      if (!sock || connectionState !== "open") {
        return sendJson(res, 503, {
          ok: false,
          error: "WhatsApp is not connected.",
        });
      }

      const raw = await readBody(req);
      const data = JSON.parse(raw || "{}");
      const name = String(data.name || "").trim();

      if (!name) {
        return sendJson(res, 400, {
          ok: false,
          error: "Group name is required.",
        });
      }

      const group = await resolveWhatsAppGroup(name);

      return sendJson(res, 200, {
        ok: true,
        group,
      });
    }

    if (req.method === "POST" && req.url === "/send") {
      if (!sock || connectionState !== "open") {
        return sendJson(res, 503, {
          ok: false,
          error: "WhatsApp is not connected.",
        });
      }

      const raw = await readBody(req);
      const data = JSON.parse(raw || "{}");

      const to = String(data.to || "").trim();
      const message = String(data.message || "").trim();

      if (!to) {
        return sendJson(res, 400, {
          ok: false,
          error: "Recipient is required.",
        });
      }

      if (!message) {
        return sendJson(res, 400, {
          ok: false,
          error: "Message is required.",
        });
      }

      let jid = to;

      if (!jid.includes("@")) {
        jid = `${jid.replace(/\D/g, "")}@s.whatsapp.net`;
      }

      const result = await sock.sendMessage(jid, {
        text: message,
      });

      return sendJson(res, 200, {
        ok: true,
        result: {
          key: result?.key || null,
          status: "sent",
          to: jid,
        },
      });
    }

    if (req.method === "POST" && req.url === "/send-media") {
      if (!sock || connectionState !== "open") {
        return sendJson(res, 503, {
          ok: false,
          error: "WhatsApp is not connected.",
        });
      }

      // base64 payload: ~25 MB file => ~34 MB body.
      const raw = await readBody(req, 40 * 1024 * 1024);
      const data = JSON.parse(raw || "{}");

      const to = String(data.to || "").trim();
      const caption = String(data.caption || "").trim();
      const fileName = String(data.file_name || "file").trim();
      const mimetype = String(data.mimetype || "application/octet-stream");
      const kind = data.kind === "image" ? "image" : "document";

      // Same rule as the rest of the bridge: media goes to DMs only.
      if (!isDirectJid(to)) {
        return sendJson(res, 400, {
          ok: false,
          error: "Media can only be sent to direct chats.",
        });
      }

      const buffer = Buffer.from(String(data.data_base64 || ""), "base64");

      if (!buffer.length) {
        return sendJson(res, 400, {
          ok: false,
          error: "File data is required.",
        });
      }

      const content =
        kind === "image"
          ? { image: buffer, mimetype, caption: caption || undefined }
          : { document: buffer, mimetype, fileName, caption: caption || undefined };

      const result = await sock.sendMessage(to, content);

      return sendJson(res, 200, {
        ok: true,
        result: { key: result?.key || null, status: "sent", to, kind },
      });
    }

    return sendJson(res, 404, {
      ok: false,
      error: "Not found.",
    });
  } catch (error) {
    console.error("[WHATSAPP] Request error:", error);

    return sendJson(res, 500, {
      ok: false,
      error: error.message || String(error),
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`[WHATSAPP] Bridge listening on ${HOST}:${PORT}`);
});

connectWhatsApp().catch(error => {
  connectionState = "error";
  lastError = error.message || String(error);
  console.error("[WHATSAPP] Startup error:", error);
});
