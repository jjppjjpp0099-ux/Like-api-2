from flask import Flask, request, jsonify
import asyncio
import aiohttp
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import json
import os
import urllib3
import random

# Protobuf imports (Make sure these .pb2 files are in the same folder)
import like_pb2
import like_count_pb2
import uid_generator_pb2

# --- CONFIGURATION ---
TOKEN_BATCH_SIZE = 20 
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- UTILITY FUNCTIONS ---

def load_tokens(server_name, for_visit=False):
    mapping = {
        "IND": ("token_ind_visit.json", "token_ind.json"),
        "BR": ("token_br_visit.json", "token_br.json"),
        "US": ("token_br_visit.json", "token_br.json"),
        "SAC": ("token_br_visit.json", "token_br.json"),
        "NA": ("token_br_visit.json", "token_br.json")
    }
    files = mapping.get(server_name, ("token_bd_visit.json", "token_bd.json"))
    path = files[0] if for_visit else files[1]
    
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                tokens = json.load(f)
                return tokens if isinstance(tokens, list) else []
    except:
        return []
    return []

def encrypt_message(plaintext):
    key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode('utf-8')

def create_like_proto(user_id, region):
    msg = like_pb2.like()
    msg.uid, msg.region = int(user_id), region
    return msg.SerializeToString()

def create_profile_proto(uid):
    msg = uid_generator_pb2.uid_generator()
    msg.krishna_, msg.teamXdarks = int(uid), 1
    return msg.SerializeToString()

# --- FAST ASYNC ENGINE ---

async def send_single_like(session, payload_hex, token_dict, url):
    token_val = token_dict.get("token", "")
    if not token_val: return 999
    
    headers = {
        'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        'Authorization': f"Bearer {token_val}",
        'Content-Type': "application/x-www-form-urlencoded",
        'ReleaseVersion': "OB52"
    }
    try:
        # Request timeout set to 5s to ensure total batch finishes within 10s
        async with session.post(url, data=bytes.fromhex(payload_hex), headers=headers, timeout=5) as resp:
            return resp.status
    except:
        return 997

async def run_parallel_likes(uid, region, url, tokens):
    payload_hex = encrypt_message(create_like_proto(uid, region))
    connector = aiohttp.TCPConnector(limit=50, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [send_single_like(session, payload_hex, t, url) for t in tokens]
        return await asyncio.gather(*tasks)

def get_profile_info(uid, server, visit_token):
    if not visit_token: return None
    enc_payload = encrypt_message(create_profile_proto(uid))
    
    url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow" if server == "IND" else \
          "https://client.us.freefiremobile.com/GetPlayerPersonalShow" if server in {"BR", "US", "SAC", "NA"} else \
          "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

    headers = {'Authorization': f"Bearer {visit_token['token']}", 'Content-Type': "application/x-www-form-urlencoded", 'ReleaseVersion': "OB52"}
    try:
        import requests
        res = requests.post(url, data=bytes.fromhex(enc_payload), headers=headers, verify=False, timeout=5)
        info = like_count_pb2.Info()
        info.ParseFromString(res.content)
        return info
    except:
        return None

# --- MAIN ROUTE ---

@app.route('/like', methods=['GET'])
def handle_like():
    uid = request.args.get("uid")
    server
