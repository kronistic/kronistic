import datetime
import logging
import os, pickle, hashlib, functools, openai
from retry import retry
from kron_app.models import User, LMCache
from kron_app import db, app


# USE_CACHE = True
# CACHE_DIR = "openai_cache"
# def disk_cache(func):
#     @functools.wraps(func)
#     def wrapper(*args, **kwargs):
#         if not os.path.exists(CACHE_DIR):
#             print("making cache dir")
#             os.makedirs(CACHE_DIR)
#         if not USE_CACHE:
#             return func(*args, **kwargs)
#         logging.info("cache check..")
#         args_bytes = pickle.dumps(args)
#         kwargs_bytes = pickle.dumps(sorted(kwargs.items()))
#         cache_key = f"{func.__name__}_{hashlib.md5(args_bytes + kwargs_bytes).hexdigest()}"        
#         cache_path = os.path.join(CACHE_DIR, f"{cache_key}.pkl")
#         if os.path.exists(cache_path):
#             with open(cache_path, "rb") as cache_file:
#                 logging.info(f"cache hit!\n")
#                 return pickle.load(cache_file)
#         logging.info("cache miss..")
#         result = func(*args, **kwargs)
#         with open(cache_path, "wb") as cache_file:
#             pickle.dump(result, cache_file)
#         return result
#     return wrapper

def clear_expired_cache_entries():
    two_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=2)
    LMCache.query.filter(LMCache.timestamp < two_weeks_ago).delete()
    db.session.commit()

def sqlalchemy_cache(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        clear_expired_cache_entries()

        args_bytes = pickle.dumps(args)
        kwargs_bytes = pickle.dumps(sorted(kwargs.items()))
        cache_key = f"{func.__name__}_{hashlib.md5(args_bytes + kwargs_bytes).hexdigest()}"

        cache_entry = LMCache.query.filter_by(cache_key=cache_key).first()

        if cache_entry:
            return pickle.loads(cache_entry.data)

        result = func(*args, **kwargs)
        new_entry = LMCache(cache_key=cache_key, data=pickle.dumps(result))
        db.session.add(new_entry)
        db.session.commit()

        return result
    return wrapper

##our main LM call, it is decorated to cache the results to disk and retry on failure
@sqlalchemy_cache
@retry(tries=3, delay=1)
def openAI(history):
    openai.api_key = app.config['OPENAI_API_KEY']
    temp = 0
    response = openai.ChatCompletion.create(model="gpt-3.5-turbo",messages=history,temperature=temp)
    return response['choices'][0]['message']['content']

def make_edit_poem(event):
    hostname = app.config['HOSTNAME']
    link=f'<a href="https://{hostname}/meeting/{event.id}">Edit in Kronistic</a>'
    if app.env == 'test' or not app.config['OPENAI_API_KEY']:
        return link
    #check whether any attendees have opted out of poems
    if any(not User.query.get(user_id).poems for user_id in event.allattendees):
        return link

    try:
        #get meeting details: title, date, start time, end time, location, attendees, description
        title = event.title
        draft_attendees = event.draft_attendees
        unavailable_ids = event.draft_unavailable
        attendees = f'Attendees:<ul>'
        for u in (User.query.get(user_id) for user_id in draft_attendees):
            attendees += f'<li>{ u.name }</li>'
        for u in (User.query.get(user_id) for user_id in unavailable_ids):
            attendees += f'<li>{ u.name } (Unavailable)</li>'
        attendees += '</ul>'
        location = event.location
        if event.is_draft():
            #if the meeting is not final provide the window, not the exact time
            # this together with caching reduces openai api calls
            start = event.window_start.date()
            end = event.window_end.date()
            meeting_deets=f"Meeting details:\nTitle: {title}\nTime: between {start} and {end}\nLocation: {location}\nAttendees: {attendees}\nDescription: {event.description}"
        else:
            #if the meeting is final provide the exact time
            start = event.draft_start
            date = start.date()
            start_time = start.time() #TODO: convert to local time?
            end_time = start_time + event.length
            meeting_deets=f"Meeting details:\nTitle: {title}\nTime: {date}, {start_time} - {end_time}\nLocation: {location}\nAttendees: {attendees}\nDescription: {event.description}"

        system=f"You are the witty and excellent scheduling assistant, Kron.\nYou will get meeting details from a user. Please write a short (3-8 line) poem about the meeting. It should be lighthearted but professional. In the poem mention that it is scheduled by Kron and include this link to edit the meeting: {link}"

        system_history = {"role": "system", "content": system}
        history=[system_history,{"role": "user", "content": meeting_deets}]

        #call chatgpt api
        response = openAI(history)
        # print(f"**openai response: {response}")
        return response

        # #add poem to description
        # event.description = f'{event.description}<p>{response}</p>'

    except Exception as e:
        #if the above doesn't work, just add the link to the description
        # print(f"**openai error: {e}")
        return link
