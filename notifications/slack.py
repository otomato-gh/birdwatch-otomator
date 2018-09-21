import os
from slackclient import SlackClient
slack_token = os.environ["SLACK_API_TOKEN"]
sc = SlackClient(slack_token)

def notify(message):
    sc.api_call(
    "chat.postMessage",
    channel="deployment",
    as_user=True,
    text=":dove_of_peace: {}".format(message)
    )

if __name__ == "__main__":
    notify()