import re
import os
import ast
import json
import datetime
from dotenv import load_dotenv

from slack import RTMClient
from chatgpt import ChatGPT

from util.postgre import sql 


load_dotenv()
postgres = sql()

## Table name will goes to env file
def toss_to_db(log_history, bot_id, table_name: str="messages"):
    global postgres
    if "blocks" in log_history.keys():
        unix_to_timestamp = datetime.datetime.fromtimestamp(float(log_history["ts"]))
        unix_to_timestamp = datetime.datetime.strftime(unix_to_timestamp, "%Y-%m-%d %H:%M:%S.%f")

        log_json = json.dumps(log_history, ensure_ascii=False).replace("'", "''")
        
        slack_id = ""
            
        try:
            slack_id = log_history["user"]
            
        except:
            slack_id = bot_id
        
        if slack_id:
            log_data = {"thread_id": log_history["thread_ts"] if "thread_ts" in log_history.keys() else log_history["event_ts"],
                        "block_id": log_history["blocks"][0]["block_id"],
                        "slack_user_id": slack_id,
                        "conversation_id": log_history["conversation_id"],
                        "parent_id": log_history["parent_id"],
                        "conversation": log_history["text"].replace("'", "''").replace("'", "''"),
                        "created_at": unix_to_timestamp,
                        "bot_answer": log_history["bot_answer"]}

            values = ", ".join([f"'{i}'" for i in log_data.values()])
            insert_format = f"INSERT INTO {table_name} VALUES ({values}, '{log_json}');"
            
            try:
                postgres.insert(insert_format)
            except:
                print(log_history)


def extract_conversation_id_from_db(thread_id, table_name: str="messages"):
    global postgres

    history_ids = postgres.read(f"SELECT conversation_id, parent_id FROM {table_name} WHERE thread_id = {thread_id} ORDER BY created_at DESC LIMIT 1;")
    
    # LIMIT 1이기에 결과값은 하나의 값만 있는 리스트가 반환됨
    conversation_id, parent_id = history_ids[0] if history_ids else (None, None)
    
    return {"conversation_id": conversation_id, "parent_id": parent_id}


def remove_user_id_in_text(text, bot_id_regex):
    return re.sub(bot_id_regex, "", text).strip()


def check_users_bot_calling(text, bot_id_regex, bot_id):
    extracted_id = re.findall(bot_id_regex, text)
    result = False
    
    if extracted_id:
        if extracted_id[0].strip() == f"<@{bot_id}>":
            result = True
            
    return result


# 지속적으로 슬랙 메세지 트래킹
@RTMClient.run_on(event="message")
def chatgptbot(**payload):
    bot_id_regex = r"\<\@[A-Z0-9]+\>\s*"

    data: dict = payload["data"]
    web_client = payload["web_client"]
    
    bot_id = os.environ["BOT_ID"]
    bot_id_in_slack_log = data.get("bot_id", "")
    
    subtype = data.get("subtype", "")
    origin_text = data.get("text", "")
    
    # 유저가 봇을 호출한 경우인지 확인 
    is_this_bot_calling = check_users_bot_calling(origin_text, bot_id_regex, bot_id)
    thread_id = data["thread_ts"] if "thread_ts" in data.keys() else data["event_ts"]
    
    history_id_keys = extract_conversation_id_from_db(thread_id)
    data.update(history_id_keys)

    
    
    response = ""
    # Bot이 입력한 채팅이 아닐 경우 + 유저가 봇을 호출한 경우 ChatGPT 동작    
    if bot_id_in_slack_log == "" and subtype == "" and is_this_bot_calling:
        # Extracting message send by the user on the slack
        text = remove_user_id_in_text(origin_text, bot_id_regex)
        
        # thread_ts: 해당 메세지 입력 시간을 파악하여 답글을 달 수 있도록 지정
        response = ChatGPT(text, 
                           history_id_keys["conversation_id"], 
                           history_id_keys["parent_id"])
        
        web_client.chat_postMessage(channel=data["channel"], 
                                    text=response["message"], 
                                    thread_ts=data["ts"])
        
        data.update(response)
    
    # DB용 값 / 봇의 대답인 경우만을 True로 함
    bot_answer = True if subtype == "bot_message" else False
    data.update({"bot_answer": bot_answer})
        
    # 봇 답변 및 유저의 봇 호출 시에만 DB 적재
    if bot_answer or is_this_bot_calling:
        toss_to_db(data, bot_id)
        
    # 슬랙 메시지 확인
#     print(data)

        
if __name__ == "__main__":
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    try:
        # RTM 클라이언트 호출 및 시작
        rtm_client = RTMClient(token=bot_token)
        print("Starter Bot connected and running!")
        rtm_client.start()
    except Exception as err:
        print(err)
