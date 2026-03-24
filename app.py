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
import time

# --- Configuration ---
TOKEN_BATCH_SIZE = 350  # Ab ye 350 likes tak handle karega
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global State for Batch Management
current_batch_indices = {}
batch_indices_lock = threading.Lock()

def get_next_batch_tokens(server_name, all_tokens):
    if not all_tokens:
        return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE:
        return all_tokens
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

def load_tokens(server_name, for_visit=False):
    suffix = "_visit.json" if for_visit else ".json"
    if server_name == "IND":
        path = f"token_ind{suffix}"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        path = f"token_br{suffix}"
    else:
        path = f"token_bd{suffix}"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) else []
    except:
        return []

def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_message = pad(plaintext, AES.block_size)
    return binascii.hexlify(cipher.encrypt(padded_message)).decode('utf-8')

def create_protobuf_message(user_id, region):
    message = like_pb2.like()
    message.uid = int(user_id)
    message.region = region
    return message.SerializeToString()

def create_protobuf_for_profile_check(uid):
    message = uid_generator_pb2.uid_generator()
    message.krishna_ = int(uid)
    message.teamXdarks = 1
    return message.SerializeToString()

# --- NEW OPTIMIZED ASYNC FUNCTIONS ---

async def send_single_like_optimized(session, encrypted_payload, token_dict, url):
    token_value = token_dict.get("token", "")
    if not token_value: return 999
    
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded",
        'ReleaseVersion': "OB52",
        'Connection': "keep-alive"
    }
    try:
        edata = bytes.fromhex(encrypted_payload)
        async with session.post(url, data=edata, headers=headers, timeout=15) as response:
            return response.status
    except:
        return 998

async def process_like_batches(uid, region, url, tokens):
    """Likes ko 10-10 ke groups mein bhejta hai taaki server block na kare"""
    payload = encrypt_message(create_protobuf_message(uid, region))
    results = []
    chunk_size = 10 # Ek baar mein sirf 10 requests
    
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(tokens), chunk_size):
            chunk = tokens[i : i + chunk_size]
            tasks = [send_single_like_optimized(session, payload, t, url) for t in chunk]
            
            chunk_results = await asyncio.gather(*tasks, return_exceptions=True)
            results.extend(chunk_results)
            
            # Anti-Spam Delay: Har 10 likes ke baad thoda intezar
            print(f"Status: {len(results)}/{len(tokens)} processed...")
            await asyncio.sleep(0.7) 
            
    return results

# --- PROFILE CHECK LOGIC ---

def make_profile_check_request(uid, server_name, token_dict):
    token_value = token_dict.get("token", "")
    if not token_value: return None
    
    urls = {
        "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
        "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    }
    url = urls.get(server_name, "https://clientbp.ggblueshark.com/GetPlayerPersonalShow")
    
    payload = encrypt_message(create_protobuf_for_profile_check(uid))
    headers = {'Authorization': f"Bearer {token_value}", 'Content-Type': "application/x-www-form-urlencoded"}
    
    try:
        response = requests.post(url, data=bytes.fromhex(payload), headers=headers, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(response.content)
        return items
    except:
        return None

# --- FLASK ROUTES ---

app = Flask(__name__)

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server = request.args.get("server_name", "").upper()
    
    if not uid or not server:
        return jsonify({"error": "Missing UID or server"}), 400

    visit_tokens = load_tokens(server, for_visit=True)
    all_tokens = load_tokens(server, for_visit=False)
    
    if not all_tokens:
        return jsonify({"error": "No tokens found"}), 500

    # Get likes BEFORE
    before_info = make_profile_check_request(uid, server, visit_tokens[0]) if visit_tokens else None
    before_count = int(before_info.AccountInfo.Likes) if before_info else 0

    # Send Likes in Batches
    like_url = "https://client.ind.freefiremobile.com/LikeProfile" if server == "IND" else \
               "https://client.us.freefiremobile.com/LikeProfile" if server in ["BR", "US"] else \
               "https://clientbp.ggblueshark.com/LikeProfile"
    
    target_tokens = get_next_batch_tokens(server, all_tokens)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process_like_batches(uid, server, like_url, target_tokens))
    finally:
        loop.close()

    # Get likes AFTER
    after_info = make_profile_check_request(uid, server, visit_tokens[0]) if visit_tokens else None
    after_count = int(after_info.AccountInfo.Likes) if after_info else before_count
    nickname = str(after_info.AccountInfo.PlayerNickname) if after_info else "N/A"

    return jsonify({
        "LikesGivenByAPI": after_count - before_count,
        "LikesafterCommand": after_count,
        "LikesbeforeCommand": before_count,
        "PlayerNickname": nickname,
        "UID": uid,
        "status": 1 if after_count > before_count else 2,
        "Note": f"Processed batch of {len(target_tokens)} tokens with Anti-Spam delays."
    })

if __name__ == '__main__':
    # Flask[async] support ke liye debug mode
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
