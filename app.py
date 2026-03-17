import os
import logging
import asyncio
import json
import threading
import random
import binascii
import urllib3
import requests
import aiohttp
from flask import Flask, request, jsonify
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from github import Github
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- IMPORT PROTO FILES ---
import like_pb2
import like_count_pb2
import uid_generator_pb2

# --- CONFIGURATION & ENV VARS ---
# Ye values Render ke 'Environment' tab se aayengi
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GITHUB_TOKEN = os.environ.get('G_TOKEN')
REPO_NAME = "jjppjjpp0099-ux/Like-api-2"
ADMIN_ID = int(os.environ.get('ADMIN_ID', 0))

TOKEN_BATCH_SIZE = 100
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global State for Batch Management
current_batch_indices = {}
batch_indices_lock = threading.Lock()

app = Flask(__name__)

# ---------------------------------------------------------
# 1. TELEGRAM BOT LOGIC (GITHUB UPDATE FEATURE)
# ---------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Bot is Online!\nFlask API aur GitHub Update dono active hain.")

async def update_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Aapko ye command use karne ki permission nahi hai.")
        return
    context.user_data['waiting_for_json'] = True
    await update.message.reply_text("📤 Theek hai! Ab `token_ind.json` ya `token_ind_visit.json` file bhejiye.")

async def handle_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_json'):
        return

    doc = update.message.document
    file_name = doc.file_name

    if file_name in ["token_ind.json", "token_ind_visit.json"]:
        status_msg = await update.message.reply_text(f"⏳ GitHub par {file_name} update ho raha hai...")
        
        try:
            # Download from Telegram
            tg_file = await doc.get_file()
            content = await tg_file.download_as_bytearray()

            # GitHub Update
            g = Github(GITHUB_TOKEN)
            repo = g.get_repo(REPO_NAME)
            contents = repo.get_contents(file_name)
            repo.update_file(contents.path, f"Update {file_name} via Bot", bytes(content), contents.sha)
            
            await status_msg.edit_text(f"✅ {file_name} successfully update ho gayi!")
            context.user_data['waiting_for_json'] = False
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {str(e)}")
    else:
        await update.message.reply_text("⚠️ Galat file! Sirf allowed JSON files hi bhejiye.")

def run_bot():
    """Bot ko background thread mein chalane ke liye function"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("update_files", update_files_command))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_docs))
    
    print("Telegram Bot starting...")
    application.run_polling()

# ---------------------------------------------------------
# 2. AAPKA PURANA LIKE API FUNCTIONS
# ---------------------------------------------------------

def get_next_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE: return all_tokens
    
    with batch_indices_lock:
        if server_name not in current_batch_indices: current_batch_indices[server_name] = 0
        current_index = current_batch_indices[server_name]
        start_index = current_index
        end_index = start_index + TOKEN_BATCH_SIZE
        if end_index > total_tokens:
            remaining = end_index - total_tokens
            batch_tokens = all_tokens[start_index:total_tokens] + all_tokens[0:remaining]
        else:
            batch_tokens = all_tokens[start_index:end_index]
        current_batch_indices[server_name] = (current_index + TOKEN_BATCH_SIZE) % total_tokens
        return batch_tokens

def get_random_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    if len(all_tokens) <= TOKEN_BATCH_SIZE: return all_tokens.copy()
    return random.sample(all_tokens, TOKEN_BATCH_SIZE)

def load_tokens(server_name, for_visit=False):
    if for_visit:
        path = "token_ind_visit.json" if server_name == "IND" else ("token_br_visit.json" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd_visit.json")
    else:
        path = "token_ind.json" if server_name == "IND" else ("token_br.json" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return []

def encrypt_message(plaintext):
    key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def create_protobuf_message(user_id, region):
    m = like_pb2.like()
    m.uid, m.region = int(user_id), region
    return m.SerializeToString()

def create_protobuf_for_profile_check(uid):
    m = uid_generator_pb2.uid_generator()
    m.krishna_, m.teamXdarks = int(uid), 1
    return m.SerializeToString()

def enc_profile_check_payload(uid):
    return encrypt_message(create_protobuf_for_profile_check(uid))

async def send_single_like_request(encrypted_like_payload, token_dict, url):
    edata = bytes.fromhex(encrypted_like_payload)
    token_value = token_dict.get("token", "")
    headers = {
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded",
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'ReleaseVersion': "OB52"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers, timeout=10) as resp:
                return resp.status
    except: return 999

async def send_likes_with_token_batch(uid, server, url, batch):
    payload = encrypt_message(create_protobuf_message(uid, server))
    tasks = [send_single_like_request(payload, t, url) for t in batch]
    return await asyncio.gather(*tasks, return_exceptions=True)

def make_profile_check_request(payload, server, token_dict):
    token = token_dict.get("token", "")
    if server == "IND": url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server in {"BR", "US", "SAC", "NA"}: url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else: url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
    
    headers = {'Authorization': f"Bearer {token}", 'Content-Type': "application/x-www-form-urlencoded"}
    try:
        response = requests.post(url, data=bytes.fromhex(payload), headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(response.content)
        return items
    except: return None

# ---------------------------------------------------------
# 3. FLASK ROUTES
# ---------------------------------------------------------

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid or not server: return jsonify({"error": "Missing params"}), 400

    visit_tokens = load_tokens(server, for_visit=True)
    all_tokens = load_tokens(server, for_visit=False)
    if not all_tokens or not visit_tokens: return jsonify({"error": "Tokens not found"}), 500

    v_token = visit_tokens[0]
    batch = get_random_batch_tokens(server, all_tokens) if use_random else get_next_batch_tokens(server, all_tokens)
    
    # Before check
    p_load = enc_profile_check_payload(uid)
    before = make_profile_check_request(p_load, server, v_token)
    b_count = int(before.AccountInfo.Likes) if before else 0

    # Sending Likes
    u_url = "https://client.ind.freefiremobile.com/LikeProfile" if server == "IND" else ("https://client.us.freefiremobile.com/LikeProfile" if server in {"BR", "US", "SAC", "NA"} else "https://clientbp.ggblueshark.com/LikeProfile")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_likes_with_token_batch(uid, server, u_url, batch))
    loop.close()

    # After check
    after = make_profile_check_request(p_load, server, v_token)
    a_count = int(after.AccountInfo.Likes) if after else b_count
    
    return jsonify({
        "LikesGivenByAPI": a_count - b_count,
        "LikesafterCommand": a_count,
        "LikesbeforeCommand": b_count,
        "PlayerNickname": str(after.AccountInfo.PlayerNickname) if after else "N/A",
        "status": 1 if a_count > b_count else 2
    })

@app.route('/token_info', methods=['GET'])
def token_info():
    servers = ["IND", "BD", "BR", "US", "SAC", "NA"]
    return jsonify({s: {"regular": len(load_tokens(s)), "visit": len(load_tokens(s, True))} for s in servers})

if __name__ == '__main__':
    # Start Bot in background
    threading.Thread(target=run_bot, daemon=True).start()
    # Start Flask
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
def token_info():
    # ... (Aapka purana token_info code)
    return jsonify({"info": "Token stats"})

# ---------------------------------------------------------
# 3. MAIN EXECUTION
# ---------------------------------------------------------

if __name__ == '__main__':
    # 1. Bot ko dusre thread mein start karein
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # 2. Flask API ko main thread mein chalayein
    # Render ke liye port os.environ se lena best hai
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
