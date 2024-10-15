import asyncio
import os
from openai import OpenAI
import json
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS, cross_origin
import time
import logging


def extract_function_names(assistant_definition):
    function_names = []
    if hasattr(assistant_definition, 'tools'):
        for tool in assistant_definition.tools:
            if hasattr(tool, 'function') and hasattr(tool.function, 'name'):
                function_names.append(tool.function.name)
    return function_names

def setin_context(data, context, key, value):
    if context in ["hiddenContext", "visibleContext", "openContext"]:
        data[context][key] = value
    else:
        raise ValueError(f"Invalid context: {context}")

def getfrom_context(data, context, key):
    if context is None or context == "":
        return data.get(key, [])
    elif context in ["hiddenContext", "visibleContext", "openContext"]:
        if key in data.get(context, {}):
            return data[context].get(key, [])
        else:
            return None
    else:
        return None

def validate_assistant(assistant_id, data, client):
    assistant_definition = client.beta.assistants.retrieve(assistant_id)
    functions = extract_function_names(assistant_definition)
    logger.info("functions", functions)
    logger.info("Validating assistant")
    expected_options = data.get('expectedOptions', [])
    for funct in functions:
        if funct not in expected_options:
            return (False, f"Function name {funct} must be in Service Cell OPTIONS" )
    return  (True, None)

def return_warning(data, warning_message):
    setin_context(data, "hiddenContext", "warning", warning_message)
    return return_option(data, "WARNING")

def return_success(data, assistant_response):
    setin_context(data, "hiddenContext", "assistant_response", assistant_response)
    return return_option(data, "SUCCESS")

def return_function_call(data, function_name):
    setin_context(data, "hiddenContext", "thread_status", "requires_action")
    return return_option(data, function_name)

def return_option(data, option):
    response = {
        "openContext": data['openContext'],
        "visibleContext": data['visibleContext'],
        "hiddenContext": data['hiddenContext'],
        "option": option
    }
    return response

app = Flask(__name__)
CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

# Ensure you log to stdout
logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)
# Adjust the logging level for the httpx logger
httpx_logger = logging.getLogger("httpx")
httpx_logger.setLevel(logging.WARNING)

@app.route("/", methods=["POST"])
def gpt():

    data = request.json

    logger.info(f"Logger: Request received")
    try:
        assistant_id = getfrom_context(data, "hiddenContext", "assistant_id")
        if assistant_id is None:
            return return_warning(data, "hiddenContext.assistant_id not found")
        
        api_key = os.getenv('OPENAI_API_KEY')
        client = OpenAI(api_key=api_key)
        
        if (not bool(getfrom_context(data, "hiddenContext", "is_assistant_valid")) or False):
            is_valid, error_message = validate_assistant(assistant_id, data, client)
            if is_valid:
                setin_context(data, "hiddenContext", "is_assistant_valid", True)
            else:
                return return_warning(data, error_message)
        
        
        # Call the validate_assistant function and unpack the return values
        
        userpromt = getfrom_context(data, "", "text")
        stored_threadid = getfrom_context(data, "hiddenContext", "thread_id")
        if (stored_threadid==None):
            #create a new thread because thread_id is not found
            thread = client.beta.threads.create(
            messages=[
            {
                "role": "user",
                "content": userpromt
            }])
            setin_context(data, "hiddenContext", "thread_id", thread.id)
            stored_threadid = thread.id
        else:
            # check status of current thread
            if ( getfrom_context(data, "hiddenContext", "thread_status") == "requires_action"):
                #add response to the existing thread
                run_id = getfrom_context(data, "hiddenContext", "run_id")
                tool_id = getfrom_context(data, "hiddenContext", "tool_id")
                function_call_result = getfrom_context(data, "hiddenContext", "function_call_result")
                function_call_result_str = json.dumps(function_call_result) if isinstance(function_call_result, dict) else str(function_call_result)
                
                tool_output = {
                "tool_call_id": tool_id,
                 "output": function_call_result_str
                }

                functionOutputrun = client.beta.threads.runs.submit_tool_outputs_and_poll(
                    thread_id=stored_threadid,
                    run_id=run_id,
                    tool_outputs=[tool_output] )
                setin_context(data, "hiddenContext", "thread_status", None)
                setin_context(data, "hiddenContext", "run_id", None)
                setin_context(data, "hiddenContext", "tool_id", None)
                setin_context(data, "hiddenContext", "function_call_result", None)
                setin_context(data, "hiddenContext", "function_arguments", None)
                if functionOutputrun.status == 'completed': 
                    #GPT response is completed
                    messages = client.beta.threads.messages.list(thread_id=stored_threadid)
                    assistant_reply = messages.data[0].content[0].text.value
                    logger.info(f"Assistant text reply: {assistant_reply}")
                    return return_success(data, assistant_reply)
                else:
                    return return_warning(data, "run thread failed")

            # Add a message to the existing thread
            client.beta.threads.messages.create(
                thread_id=stored_threadid,
                role="user",
                content=userpromt
            )

        logger.info("Creating a new run")
        run = client.beta.threads.runs.create_and_poll(
            thread_id=stored_threadid,
            assistant_id=assistant_id )
        messages = client.beta.threads.messages.list(thread_id=stored_threadid)
        if run.status == 'completed': 
            #GPT response is completed
            assistant_reply = messages.data[0].content[0].text.value
            logger.info(f"Logger: Assistant text reply: {assistant_reply}")
            return return_success(data, assistant_reply)
        
        elif run.status == 'requires_action':
            required_action = run.required_action
            if required_action.type == 'submit_tool_outputs':
                tool_call = required_action.submit_tool_outputs.tool_calls[0]
                if tool_call.type == 'function':
                    tool_id = tool_call.id
                    function_name = tool_call.function.name
                    function_arguments = tool_call.function.arguments
                    
                     # Extract text and function calling instructions
                    logger.info(f"Function name: {function_name}")
                    logger.info(f"Function arguments: {function_arguments}")
                            

                    setin_context(data, "hiddenContext", "function_arguments", json.loads(function_arguments))
                    setin_context(data, "hiddenContext", "thread_status", "requires_action")
                    setin_context(data, "hiddenContext", "tool_id", tool_id)
                    setin_context(data, "hiddenContext", "run_id", run.id)
                    #setin_context(data, "hiddenContext", "assistant_response", f"calling function {function_name}")
                    return return_option(data, function_name)
                    #return return_success(data)
        
        else:
            return return_warning(data, "run thread failed")

    
    
    except Exception as e:
        logger.info("Exception occurred:", e)
        return return_warning(data, "Exception occurred")

@app.route("/test", methods=["GET"])
def test():
    logger.info("GET request received. The server is running correctly")
    return jsonify({"message": "GET request received. The server is running correctly."})



if __name__ == "__main__":
    port = int(os.getenv('PORT', 8080))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port)