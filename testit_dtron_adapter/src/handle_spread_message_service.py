#!/usr/bin/env python

import importlib
import re
import yaml
from collections import defaultdict

import rospy
from testit_dtron_adapter.srv import HandleSpreadMessageResponse, HandleSpreadMessage


def dynamic_import(path):
    path_list = path.split('.')
    module = '.'.join(path_list[:-1])
    function = path_list[-1]

    return getattr(importlib.import_module(module), function)


def get_attribute(value, path):
    for attribute in path.split('.'):
        value = getattr(value, attribute)
    return value


def set_attribute(object, field_path, value):
    field_path_list = field_path.split('.')
    for field in field_path_list[:-1]:
        object = getattr(object, field)
    setattr(object, field_path_list[-1], value)


def compose_message(fields):
    if not fields:
        return
    msg = fields[0]['type']()
    for field in fields:
        set_attribute(msg, field['field'], field['value'])
    return msg


def success(result, feedback):
    return feedback.get('success', result) == result or re.match(
        str(feedback['success']),
        str(result)) is not None


class Reference:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value

    def get(self):
        return self.value

    def remove(self):
        self.value = None


def get_topic_sender_responder(identifier, id_type, feedback):
    publishers = {}
    response = Reference()

    def send(msg):
        if identifier not in publishers:
            publishers[identifier] = rospy.Publisher(identifier, id_type, queue_size=1)
            rospy.sleep(1)
        rospy.loginfo("Publishing message to topic " + identifier + " :")
        rospy.loginfo(str(msg))
        publishers[identifier].publish(msg)
        feedback_topic = feedback.get('topic')
        response.set(rospy.wait_for_message(feedback_topic, dynamic_import(feedback.get('type'))))

    def get_response():
        while response.get() is None:
            rospy.sleep(0.1)
        result = get_attribute(response.get(), feedback.get('field', ''))
        response.remove()
        rospy.loginfo("Result:")
        rospy.loginfo(result)
        return success(result, feedback)

    return send, get_response


def get_service_sender_responder(identifier, id_type, feedback):
    result = []

    def send(msg):
        rospy.wait_for_service(identifier)
        service = rospy.ServiceProxy(identifier, id_type)
        response = service(msg)
        result.append(response)

    def get_response():
        return success(result.pop(), feedback)

    return send, get_response


def send_messages(variables):
    fields_by_topic = defaultdict(list)
    senders_by_id = {}
    receivers_by_id = {}

    for variable in variables:
        mode = variable['mode']
        field_name = variable['variable']
        identifier = variable['identifier']
        value = variable['value']
        feedback = variable.get('feedback', {})
        id_type_name = variable['type']
        id_type = dynamic_import(id_type_name)

        get_sender_responder = None
        if mode == 'service':
            get_sender_responder = get_service_sender_responder
            identifier = variable['proxy']
        elif mode == 'topic':
            get_sender_responder = get_topic_sender_responder

        if not get_sender_responder:
            continue

        sender, receiver = get_sender_responder(identifier, id_type, feedback)
        senders_by_id[identifier] = sender
        receivers_by_id[identifier] = receiver
        fields_by_topic[identifier].append({'field': field_name, 'value': value, 'type': id_type})

    response = True
    for identifier in senders_by_id:
        msg = compose_message(fields_by_topic[identifier])
        senders_by_id[identifier](msg)
        response = response and receivers_by_id[identifier]()

    return response


def handle_spread_message(msg):
    rospy.loginfo("Request:")
    rospy.loginfo(msg.input)
    args = yaml.load(msg.input)
    message_name = args.get("name", None)

    if message_name is None:
        rospy.logerr("Message not received.")
        return

    variables = []
    for key in args:
        if key == "name":
            continue
        param = args[key]
        variable = rospy.get_param("/commands/i_{}/{}={}".format(message_name, key, param))
        variables.append(variable)

    constants_by_field = rospy.get_param("/constants/i_{}".format(message_name))
    for field in constants_by_field:
        variable = constants_by_field[field]
        variables.append(variable)

    return HandleSpreadMessageResponse(send_messages(variables))


def handle_spread_message_server():
    rospy.init_node("handle_spread_message", anonymous=True)
    rospy.loginfo("Starting spread message handler")
    _ = rospy.Service('/testit/dtron_adapter/handle_spread_message', HandleSpreadMessage, handle_spread_message)
    rospy.spin()


if __name__ == '__main__':
    handle_spread_message_server()
