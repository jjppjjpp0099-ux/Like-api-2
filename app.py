@app.route('/like', methods=['GET'])
def handle_requests():
    uid_param = request.args.get("uid")
    server_name_param = request.args.get("server_name", "").upper()
    use_random = request.args.get("random", "false").lower() == "true"

    if not uid_param or not server_name_param:
        return jsonify({"error": "UID and server_name are required"}), 400

    # Load visit token for profile checking
    visit_tokens = load_tokens(server_name_param, for_visit=True)
    if not visit_tokens:
        return jsonify({"error": f"No visit tokens loaded for server {server_name_param}."}), 500
    
    visit_token = visit_tokens[0] if visit_tokens else None
    all_available_tokens = load_tokens(server_name_param, for_visit=False)
    if not all_available_tokens:
        return jsonify({"error": f"No tokens loaded for server {server_name_param}."}), 500

    # Get token batch
    tokens_for_like_sending = get_random_batch_tokens(server_name_param, all_available_tokens) if use_random else get_next_batch_tokens(server_name_param, all_available_tokens)
    
    encrypted_player_uid_for_profile = enc_profile_check_payload(uid_param)
    before_info = make_profile_check_request(encrypted_player_uid_for_profile, server_name_param, visit_token)
    before_like_count = int(before_info.AccountInfo.Likes) if before_info and hasattr(before_info, 'AccountInfo') else 0

    # Determine like API URL
    if server_name_param == "IND":
        like_api_url = "https://client.ind.freefiremobile.com/LikeProfile"
    elif server_name_param in {"BR", "US", "SAC", "NA"}:
        like_api_url = "https://client.us.freefiremobile.com/LikeProfile"
    else:
        like_api_url = "https://clientbp.ggblueshark.com/LikeProfile"

    if tokens_for_like_sending:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(send_likes_with_token_batch(uid_param, server_name_param, like_api_url, tokens_for_like_sending))
        finally:
            loop.close()
    
    after_info = make_profile_check_request(encrypted_player_uid_for_profile, server_name_param, visit_token)
    after_like_count = before_like_count
    player_nickname_from_profile = "N/A"
    
    if after_info and hasattr(after_info, 'AccountInfo'):
        after_like_count = int(after_info.AccountInfo.Likes)
        player_nickname_from_profile = str(after_info.AccountInfo.PlayerNickname) if after_info.AccountInfo.PlayerNickname else "N/A"

    # Prepare bot.py compatible JSON
    response_data = {
        "basicInfo": {
            "nickname": player_nickname_from_profile,
            "level": "unknown",               # API me level available nahi
            "liked": before_like_count,       # Before likes
            "rank": "unknown"                 # API me rank available nahi
        },
        "socialInfo": {
            "signature": f"Used visit token for profile check and {'random' if use_random else 'rotating'} batch of {len(tokens_for_like_sending)} tokens for like sending."
        },
        "status": 1 if after_like_count > 0 else 0
    }

    return jsonify(response_data)