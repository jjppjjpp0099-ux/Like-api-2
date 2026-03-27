from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
import threading
import urllib3
import random
import os
import time

# --- [ CONFIGURATION & GLOBALS ] ---
TOKEN_BATCH_SIZE = 100
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

current_batch_indices = {}
batch_indices_lock = threading.Lock()

app = Flask(__name__)

# --- [ NEW: KEEP-ALIVE LOGIC ] ---

@app.route('/keep_alive')
def keep_alive():
    return jsonify({"status": "Bot is awake and monitoring", "time": time.ctime()}), 200

def self_ping_loop():
    """Bot ko active rakhne ke liye khud ko ping karne ka logic"""
    # Render app ka URL environment variable se le raha hai ya default
    url = os.getenv("RENDER_EXTERNAL_URL", "http://0.0.0.0:5001") + "/keep_alive"
    while True:
        try:
            requests.get(url, timeout=5)
        except:
            pass
        time.sleep(300) # Har 5 minute mein

# --- [ YOUR ORIGINAL FUNCTIONS - NO CHANGES ] ---

def get_next_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE: return all_tokens
    with batch_indices_lock:
        if server_name not in current_batch_indices:
            current_batch_indices[server_name] = 0
        current_index = current_batch_indices[server_name]
        start_index = current_index
        end_index = start_index + TOKEN_BATCH_SIZE
        if end_index > total_tokens:
            remaining = end_index - total_tokens
            batch_tokens = all_tokens[start_index:total_tokens] + all_tokens[0:remaining]
        else:
            batch_tokens = all_tokens[start_index:end_index]
        next_index = (current_index + TOKEN_BATCH_SIZE) % total_tokens
        current_batch_indices[server_name] = next_index
        return batch_tokens

def get_random_batch_tokens(server_name, all_tokens):
    if not all_tokens: return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE: return all_tokens.copy()
    return random.sample(all_tokens, TOKEN_BATCH_SIZE)

def load_tokens(server_name, for_visit=False):
    # (Aapka original logic jaisa tha waisa hi hai)
    if for_visit:
        if server_name == "IND": path = "token_ind_visit.json"
        elif server_name in {"BR", "US", "SAC", "NA"}: path = "token_br_visit.json"
        else: path = "token_bd_visit.json"
    else:
        if server_name == "IND": path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}: path = "token_br.json"
        else: path = "token_bd.json"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) else []
    except: return []

def encrypt_message(plaintext):
    key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def create_protobuf_message(user_id, region):
    message = like_pb2.like()
    message.uid, message.region = int(user_id), region
    return message.SerializeToString()

def create_protobuf_for_profile_check(uid):
    message = uid_generator_pb2.uid_generator()
    message.krishna_, message.teamXdarks = int(uid), 1
    return message.SerializeToString()

def enc_profile_check_payload(uid):
    return encrypt_message(create_protobuf_for_profile_check(uid))

async def send_single_like_request(encrypted_like_payload, token_dict, url):
    edata = bytes.fromhex(encrypted_like_payload)
    token_value = token_dict.get("token", "")
    if not token_value: return 999
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded",
        'ReleaseVersion': "OB52"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                return response.status
    except: return 997

async def send_likes_with_token_batch(uid, server_region_for_like_proto, like_api_url, token_batch_to_use):
    if not token_batch_to_use: return []
    encrypted_like_payload = encrypt_message(create_protobuf_message(uid, server_region_for_like_proto))
    tasks = [send_single_like_request(encrypted_like_payload, t, like_api_url) for t in token_batch_to_use]
    return await asyncio.gather(*tasks, return_exceptions=True)

def make_profile_check_request(encrypted_profile_payload, server_name, token_dict):
    token_value = token_dict.get("token", "")
    if not token_value: return None
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server_name == "IND" else \
          ("https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server_name in {"BR", "US", "SAC", "NA"} else \
           "https://clientbp.ggblueshark.com/GetPlayerPersonalShow")
    try:
        r = requests.post(url, data=bytes.fromhex(encrypted_profile_payload), 
                         headers={'Authorization': f"Bearer {token_value}", 'Content-Type': "application/x-www-form-urlencoded"}, 
                         verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(r.content)
        return items
    except: return None

# --- [ ROUTES ] ---

@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name_param = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid_param or not server_name_param:
        return jsonify({"error": "UID and server_name are required"}), 400

    visit_tokens = load_tokens(server_name_param, for_visit=True)
    all_available_tokens = load_tokens(server_name_param, for_visit=False)

    if not all_available_tokens:
        return jsonify({"error": "No tokens loaded"}), 500

    tokens_for_like_sending = get_random_batch_tokens(server_name_param, all_available_tokens) if use_random else \
                              get_next_batch_tokens(server_name_param, all_available_tokens)
    
    visit_token = visit_tokens[0] if visit_tokens else None
    enc_payload = enc_profile_check_payload(uid_param)
    
    # Before check
    before_info = make_profile_check_request(enc_payload, server_name_param, visit_token)
    before_count = int(before_info.AccountInfo.Likes) if before_info else 0

    # Sending likes
    like_url = "https://client.ind.freefiremobile.com/LikeProfile" if server_name_param == "IND" else \
               ("https://client.us.freefiremobile.com/LikeProfile" if server_name_param in {"BR", "US", "SAC", "NA"} else \
                "https://clientbp.ggblueshark.com/LikeProfile")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(send_likes_with_token_batch(uid_param, server_name_param, like_url, tokens_for_like_sending))
    loop.close()
        
    # After check
    after_info = make_profile_check_request(enc_payload, server_name_param, visit_token)
    after_count = int(after_info.AccountInfo.Likes) if after_info else before_count
    nickname = str(after_info.AccountInfo.PlayerNickname) if after_info else "N/A"

    return jsonify({
        "LikesGivenByAPI": after_count - before_count,
        "LikesafterCommand": after_count,
        "LikesbeforeCommand": before_count,
        "PlayerNickname": nickname,
        "UID": int(uid_param),
        "status": 1 if (after_count - before_count) > 0 else 2
    })

@app.route('/token_info', methods=['GET'])
def token_info():
    servers = ["IND", "BD", "BR", "US", "SAC", "NA"]
    return jsonify({s: {"regular": len(load_tokens(s)), "visit": len(load_tokens(s, True))} for s in servers})

# --- [ EXECUTION LOGIC FOR RENDER ] ---

if __name__ == '__main__':
    # Local run logic
    threading.Thread(target=self_ping_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5001)
else:
    # Render/Gunicorn production logic
    # Ye thread bot ko background mein active rakhega
    threading.Thread(target=self_ping_loop, daemon=True).start()
