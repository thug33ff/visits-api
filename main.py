# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
import asyncio
import aiohttp
import base64
import json
from pymongo import MongoClient
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from config import REGION_CONFIG, DB_NAME, MONGO_URI, MAX_USAGE,LICENCE_API,LICENCE_ID,SCOPE
from proto import (
    GetPlayerPersonalShowReq_pb2,
    GetPlayerPersonalShowResp_pb2,
    RequestAddingFriendreq_pb2
)

app = Flask(__name__)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

async def check_key(session, key: str):
    try:
        if not session:
                return False

        url = f"{LICENCE_API}/{LICENCE_ID}/{key}/verify?scope={SCOPE}"

        async with session.get(url, timeout=10) as r:
                if r.status != 200:
                    return False

                data = await r.json()
                return data.get("valid", False)

    except Exception as e:
        print("check key error:", e)
        return False

def encrypt_aes(data: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(data, AES.block_size))

def get_account_id(token: str):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded.decode())
        return int(data.get("account_id"))
    except Exception as e:
        print("JWT error:", e)
        return None

def fetch_tokens(region):
    config = REGION_CONFIG.get(region)
    if not config:
        return []
    return [t["token"] for t in db[config["tokens"]].find({}, {"_id": 0, "token": 1})]

def parse_protobuf_response(data: bytes):
    try:
        info = GetPlayerPersonalShowResp_pb2.GetPlayerPersonalShowResponse()
        info.ParseFromString(data)
        b = info.basicinfo

        return {
            "uid": b.accountid or 0,
            "nickname": b.nickname or "",
            "likes": b.liked or 0,
            "region": b.region or "",
            "level": b.level or 0
        }
    except Exception as e:
        app.logger.error(f"Protobuf error: {e}")
        return None

async def get_header(token):
    return {
        "Authorization": f"Bearer {token}",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB53",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": "16",
        "User-Agent": "Dalvik/2.1.0 (Android 9)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }

async def visit(session, url, token, uid, payload, sem):
    async with sem:
        try:
            headers = await get_header(token)

            async with session.post(url,headers=headers,data=payload,ssl=False,timeout=10) as resp:
                if resp.status == 200:
                    return True, await resp.read()
                return False, None

        except Exception as e:
            app.logger.error(f"visit error {token[-5:]}: {e}")
            return False, None

async def send_until_success(tokens, uid, region, target_success=500):
    url = REGION_CONFIG[region]["url_visit"]

    connector = aiohttp.TCPConnector(limit=20)
    sem = asyncio.Semaphore(20)

    success = 0
    sent = 0
    player_info = None

    msg = GetPlayerPersonalShowReq_pb2.GetPlayerPersonalShowRequest()
    msg.account_id = int(uid)
    msg.field2 = 7
    msg.field4 = 1

    payload = encrypt_aes(msg.SerializeToString())

    async with aiohttp.ClientSession(connector=connector) as session:
        while success < target_success:

            batch = min(target_success - success, len(tokens))

            tasks = [
                visit(session,url,tokens[(sent+i)%len(tokens)],uid,payload,sem)
                for i in range(batch)
            ]

            results = await asyncio.gather(*tasks)

            if player_info is None:
                for ok, resp in results:
                    if ok and resp:
                        player_info = parse_protobuf_response(resp)
                        break

            success += sum(1 for r,_ in results if r)
            sent += batch

            await asyncio.sleep(0.5)

    return success, sent, player_info

async def send_friend_request(session, uid, url, token):
    try:
        msg = RequestAddingFriendreq_pb2.RequestAddingFriendrequests()
        msg.account_id = get_account_id(token)
        msg.requests_id = int(uid)
        msg.type = 22

        payload = encrypt_aes(msg.SerializeToString())
        headers = await get_header(token)

        async with session.post(url,headers=headers,data=payload,timeout=20) as resp:
            return resp.status == 200

    except Exception as e:
        app.logger.error(f"friend error {token[-5:]}: {e}")
        return False


@app.route("/visits", methods=["GET"])
def send_visits():
    uid = request.args.get("uid")
    region = request.args.get("region")
    key = request.args.get("key")

    missing = [k for k, v in {
        "uid": uid,
        "region": region,
        "key": key
    }.items() if not v]

    if missing:
        return jsonify({
            "error": f"missing params: {', '.join(missing)}", }), 400

    region = region.upper()
    if region not in REGION_CONFIG:
        region = "ME"

    async def run():
        async with aiohttp.ClientSession() as session:

            # 🔐 CHECK KEY
            if not await check_key(session, key):
                return None

            tokens = fetch_tokens(region)
            if not tokens:
                return "no_tokens"

            success, sent, info = await send_until_success(
                tokens, uid, region, 500
            )

            if not info:
                return "decode_failed"

            return {
                "success": success,
                "fail": sent - success,
                **info
            }

    result = asyncio.run(run())

    if result is None:
        return jsonify({"error": "invalid key"}), 403

    if result == "no_tokens":
        return jsonify({"error": "no tokens"}), 500

    if result == "decode_failed":
        return jsonify({"error": "decode failed"}), 500

    return jsonify(result)


@app.route("/send_requests", methods=["GET"])
async def send_requests():
    uid = request.args.get("uid")
    region = request.args.get("region")
    key = request.args.get("key")

    missing = [k for k, v in {
        "uid": uid,
        "region": region,
        "key": key
    }.items() if not v]

    if missing:
        return jsonify({
            "error": f"missing params: {', '.join(missing)}", }), 400
    
    region = region.upper()
    if region not in REGION_CONFIG:
        return jsonify({"error": "bad region"}), 400

    config = REGION_CONFIG[region]

    async with aiohttp.ClientSession() as session:

        # 🔐 CHECK KEY
        if not await check_key(session, key):
            return jsonify({"error": "invalid key"}), 403

        tokens = fetch_tokens(region)
        if not tokens:
            return jsonify({"error": "no tokens"}), 500

        url_visit = config["url_visit"]
        player_info = None

        msg = GetPlayerPersonalShowReq_pb2.GetPlayerPersonalShowRequest()
        msg.account_id = int(uid)
        msg.field2 = 7
        msg.field4 = 1

        payload = encrypt_aes(msg.SerializeToString())

        for i in range(1, MAX_USAGE):
            try:
                headers = await get_header(tokens[i])

                async with session.post(
                    url_visit,headers=headers,data=payload,timeout=10
                ) as r:

                    if r.status == 200:
                        player_info = parse_protobuf_response(await r.read())
                        break

            except Exception as e:
                app.logger.warning(f"token error {i}: {e}")

        if not player_info:
            return jsonify({"error": "no player"}), 500

        tasks = [
            send_friend_request(session, uid, config["url_spam"], t)
            for t in tokens[:110]
        ]

        results = await asyncio.gather(*tasks)

        return jsonify({
            "success": sum(results),
            "fail": len(results) - sum(results),
            **player_info
        })
    


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6059, debug=True)