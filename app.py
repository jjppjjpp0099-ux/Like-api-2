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

# --- CONFIGURATION ---
TOKEN_BATCH_SIZE = 20 
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global State for Batch Management
current_batch_indices = {}
batch_indices_lock = threading.Lock()

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
    if for_visit:
        path = "token_ind_visit.json" if server_name == "IND" else \
               "token_br_visit.json" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd_visit.json"
    else:
        path = "token_ind.json" if server_name == "IND" else \
               "token_br.json" if server_name in {"BR", "US", "SAC", "NA"} else "token_bd.json"
    try:
        with open(path, "r") as f:
            tokens = json.load(f)
            return tokens if isinstance(tokens, list) else []
    except Exception: return []

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

async def send_single_like_request(encrypted_payload, token_dict, url):
    edata = bytes.fromhex(encrypted_payload)
    token = token_dict.get("token", "")
    if not token: return 999
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token}",
        'Content-Type': "application/x-www-form-urlencoded",
        'ReleaseVersion': "OB52"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                return r.status
    except Exception: return 997

async def send_likes_with_token_batch(uid, server_region, like_api_url, token_batch):
    if not token_batch: return []
    payload = encrypt_message(create_protobuf_message(uid, server_region))
    tasks = [send_single_like_request(payload, t, like_api_url) for t in token_batch]
    return await asyncio.gather(*tasks, return_exceptions=True)

def make_profile_check_request(encrypted_payload, server_name, token_dict):
    token = token_dict.get("token", "")
    if not token: return None
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server_name == "IND" else \
          "https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server_name in {"BR", "US", "SAC", "NA"} else \
          "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
    try:
        r = requests.post(url, data=bytes.fromhex(encrypted_payload), headers={'Authorization': f"Bearer {token}"}, verify=False, timeout=10)
        items = like_count_pb2.Info()
        items.ParseFromString(r.content)
        return items
    except Exception: return None

app = Flask(__name__)

@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name_param = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid_param or not server_name_param:
        return jsonify({"error": "UID and server_name are required"}), 400

    visit_tokens = load_tokens(server_name_param, for_visit=True)
    all_available_tokens = load_tokens(server_name_param, for_visit=False)
    
    if not visit_tokens or not all_available_tokens:
        return jsonify({"error": "Tokens not loaded"}), 500

    tokens_to_use = get_random_batch_tokens(server_name_param, all_available_tokens) if use_random else \
                    get_next_batch_tokens(server_name_param, all_available_tokens)
    
    enc_profile_payload = enc_profile_check_payload(uid_param)
    
    # Check BEFORE
    before_info = make_profile_check_request(enc_profile_payload, server_name_param, visit_tokens[0])
    before_like_count = int(before_info.AccountInfo.Likes) if before_info and hasattr(before_info, 'AccountInfo') else 0

    # Fire Likes
    like_url = "https://client.ind.freefiremobile.com/LikeProfile" if server_name_param == "IND" else \
               "https://client.us.freefiremobile.com/LikeProfile" if server_name_param in {"BR", "US", "SAC", "NA"} else \
               "https://clientbp.ggblueshark.com/LikeProfile"

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_likes_with_token_batch(uid_param, server_name_param, like_url, tokens_to_use))
    finally: loop.close()
        
    # Check AFTER
    after_info = make_profile_check_request(enc_profile_payload, server_name_param, visit_tokens[0])
    
    after_like_count = before_like_count
    player_nickname = "N/A"
    actual_uid = int(uid_param)

    if after_info and hasattr(after_info, 'AccountInfo'):
        after_like_count = int(after_info.AccountInfo.Likes)
        actual_uid = int(after_info.AccountInfo.UID)
        player_nickname = str(after_info.AccountInfo.PlayerNickname) or "N/A"

    increment = after_like_count - before_like_count
    request_status = 1 if increment > 0 else (2 if increment == 0 else 3)

    return jsonify({
        "LikesGivenByAPI": increment,
        "LikesafterCommand": after_like_count,
        "LikesbeforeCommand": before_like_count,
        "PlayerNickname": player_nickname,
        "UID": actual_uid,
        "status": request_status,
        "Note": f"Used batch of {len(tokens_to_use)} tokens."
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
