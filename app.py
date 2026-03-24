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

# --- CONFIGURATION ---
# Humne 20 rakha hai taaki user ko baar-baar likes mil sakein bina timeout ke
TOKEN_BATCH_SIZE = 20
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Global State for Batch Management (Aapke original code ki tarah)
current_batch_indices = {}
batch_indices_lock = threading.Lock()

app = Flask(__name__)

def get_next_batch_tokens(server_name, all_tokens):
    """Aapka original rotating logic (Optional use)"""
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

def get_random_batch_tokens(server_name, all_tokens):
    """BEST FOR VERCEL: Har baar naye 20 tokens uthayega"""
    if not all_tokens:
        return []
    total_tokens = len(all_tokens)
    if total_tokens <= TOKEN_BATCH_SIZE:
        return all_tokens.copy()
    return random.sample(all_tokens, TOKEN_BATCH_SIZE)

def load_tokens(server_name, for_visit=False):
    """Full path logic as per your original file"""
    if for_visit:
        if server_name == "IND":
            path = "token_ind_visit.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br_visit.json"
        else:
            path = "token_bd_visit.json"
    else:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br.json"
        else:
            path = "token_bd.json"

    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                tokens = json.load(f)
                if isinstance(tokens, list) and all(isinstance(t, dict) and "token" in t for t in tokens):
                    print(f"Loaded {len(tokens)} tokens from {path} for server {server_name}")
                    return tokens
    except Exception as e:
        print(f"Error loading tokens: {e}")
    return []

def encrypt_message(plaintext):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_message = pad(plaintext, AES.block_size)
    encrypted_message = cipher.encrypt(padded_message)
    return binascii.hexlify(encrypted_message).decode('utf-8')

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

def enc_profile_check_payload(uid):
    protobuf_data = create_protobuf_for_profile_check(uid)
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

async def send_single_like_request(session, encrypted_like_payload, token_dict, url):
    edata = bytes.fromhex(encrypted_like_payload)
    token_value = token_dict.get("token", "")
    if not token_value:
        return 999

    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Connection': "Keep-Alive",
        'Accept-Encoding': "gzip",
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded",
        'X-Unity-Version': "2018.4.11f1",
        'ReleaseVersion': "OB52"
    }
    try:
        async with session.post(url, data=edata, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as response:
            return response.status
    except Exception as e:
        print(f"Like Error: {e}")
        return 997

async def send_likes_with_token_batch(uid, region, like_api_url, token_batch_to_use):
    if not token_batch_to_use:
        return []

    like_protobuf_payload = create_protobuf_message(uid, region)
    encrypted_like_payload = encrypt_message(like_protobuf_payload)
    
    tasks = []
    # Using a shared session for maximum speed on Vercel
    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        for token_dict in token_batch_to_use:
            tasks.append(send_single_like_request(session, encrypted_like_payload, token_dict, like_api_url))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

def decode_protobuf_profile_info(binary_data):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary_data)
        return items
    except Exception as e:
        print(f"Protobuf Decode Error: {e}")
        return None

def make_profile_check_request(encrypted_profile_payload, server_name, token_dict):
    token_value = token_dict.get("token", "")
    if not token_value:
        return None

    if server_name == "IND":
        url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

    edata = bytes.fromhex(encrypted_profile_payload)
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token_value}",
        'Content-Type': "application/x-www-form-urlencoded",
        'ReleaseVersion': "OB52"
    }
    try:
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
        if response.status_code == 200:
            return decode_protobuf_profile_info(response.content)
    except Exception as e:
        print(f"Profile Check Error: {e}")
    return None

@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name_param = request.args.get("server_name", "").upper()

    if not uid_param or not server_name_param:
        return jsonify({"error": "UID and server_name are required"}), 400

    # Visit tokens for profile info (Nickname etc.)
    visit_tokens = load_tokens(server_name_param, for_visit=True)
    all_available_tokens = load_tokens(server_name_param, for_visit=False)

    if not visit_tokens or not all_available_tokens:
        return jsonify({"error": "Tokens not found for this server"}), 500

    # Selection logic: Pick 20 Random tokens for multiple uses
    tokens_for_like_sending = get_random_batch_tokens(server_name_param, all_available_tokens)
    visit_token = visit_tokens[0]

    encrypted_player_uid_for_profile = enc_profile_check_payload(uid_param)
    
    # Check likes before command
    before_info = make_profile_check_request(encrypted_player_uid_for_profile, server_name_param, visit_token)
    before_like_count = int(before_info.AccountInfo.Likes) if (before_info and hasattr(before_info, 'AccountInfo')) else 0
    
    print(f"Before: {before_like_count} likes")

    # API Like URL
    if server_name_param == "IND":
        like_api_url = "https://client.ind.freefiremobile.com/LikeProfile"
    elif server_name_param in {"BR", "US", "SAC", "NA"}:
        like_api_url = "https://client.us.freefiremobile.com/LikeProfile"
    else:
        like_api_url = "https://clientbp.ggblueshark.com/LikeProfile"

    # Start Async Engine
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(send_likes_with_token_batch(uid_param, server_name_param, like_api_url, tokens_for_like_sending))
    finally:
        loop.close()

    # Check likes after command
    after_info = make_profile_check_request(encrypted_player_uid_for_profile, server_name_param, visit_token)
    
    after_like_count = before_like_count
    player_nickname = "N/A"
    actual_uid = int(uid_param)

    if after_info and hasattr(after_info, 'AccountInfo'):
        after_like_count = int(after_info.AccountInfo.Likes)
        player_nickname = str(after_info.AccountInfo.PlayerNickname)
        actual_uid = int(after_info.AccountInfo.UID)

    likes_increment = after_like_count - before_like_count
    
    return jsonify({
        "LikesGivenByAPI": likes_increment,
        "LikesafterCommand": after_like_count,
        "LikesbeforeCommand": before_like_count,
        "PlayerNickname": player_nickname,
        "UID": actual_uid,
        "status": 1 if likes_increment > 0 else 2,
        "Note": f"Used {len(tokens_for_like_sending)} tokens."
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
