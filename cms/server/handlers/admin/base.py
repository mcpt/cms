#!/usr/bin/env python2
# -*- coding: utf-8 -*-

# Contest Management System - http://cms-dev.github.io/
# Copyright © 2010-2013 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2015 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2012 Matteo Boscariol <boscarim@hotmail.com>
# Copyright © 2012-2014 Luca Wehrstedt <luca.wehrstedt@gmail.com>
# Copyright © 2014 Artem Iglikov <artem.iglikov@gmail.com>
# Copyright © 2014 Fabian Gundlach <320pointsguy@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Base class for all handlers in AWS, and some utility functions.

"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import json
import logging
import os
import traceback

from datetime import datetime, timedelta

import tornado.web
import tornado.locale

from sqlalchemy.exc import IntegrityError

from cms import config, ServiceCoord, get_service_shards, get_service_address
from cms.db import Contest, Participation, Question, Session, \
    SubmissionFormatElement, Task, User
from cms.grading.tasktypes import get_task_type_class
from cms.grading.scoretypes import get_score_type_class
from cms.server import CommonRequestHandler, file_handler_gen, get_url_root
from cmscommon.datetime import make_datetime, make_timestamp


logger = logging.getLogger(__name__)


def argument_reader(func, empty=None):
    """Return an helper method for reading and parsing form values.

    func (function): the parser and validator for the value.
    empty (object): the value to store if an empty string is retrieved.

    return (function): a function to be used as a method of a
        RequestHandler.

    """
    def helper(self, dest, name, empty=empty):
        """Read the argument called "name" and save it in "dest".

        self (RequestHandler): a thing with a get_argument method.
        dest (dict): a place to store the obtained value.
        name (string): the name of the argument and of the item.
        empty (object): overrides the default empty value.

        """
        value = self.get_argument(name, None)
        if value is None:
            return
        if value == "":
            dest[name] = empty
        else:
            dest[name] = func(value)
    return helper


def parse_int(value):
    """Parse and validate an integer."""
    try:
        return int(value)
    except:
        raise ValueError("Can't cast %s to int." % value)


def parse_timedelta_sec(value):
    """Parse and validate a timedelta (as number of seconds)."""
    try:
        return timedelta(seconds=float(value))
    except:
        raise ValueError("Can't cast %s to timedelta." % value)


def parse_timedelta_min(value):
    """Parse and validate a timedelta (as number of minutes)."""
    try:
        return timedelta(minutes=float(value))
    except:
        raise ValueError("Can't cast %s to timedelta." % value)


def parse_datetime(value):
    """Parse and validate a datetime (in pseudo-ISO8601)."""
    if '.' not in value:
        value += ".0"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
    except:
        raise ValueError("Can't cast %s to datetime." % value)


def parse_ip_address_or_subnet(value):
    """Validate an IP address or subnet."""
    address, sep, subnet = value.partition("/")
    if sep != "":
        subnet = int(subnet)
        assert 0 <= subnet < 32
    fields = address.split(".")
    assert len(fields) == 4
    for field in fields:
        num = int(field)
        assert 0 <= num < 256
    return value


class BaseHandler(CommonRequestHandler):
    """Base RequestHandler for this application.

    All the RequestHandler classes in this application should be a
    child of this class.

    """

    REMOVE_FROM_CONTEST = "Remove from contest"
    MOVE_UP = "Move up"
    MOVE_DOWN = "Move down"

    def try_commit(self):
        """Try to commit the current session.

        If not successful display a warning in the webpage.

        return (bool): True if commit was successful, False otherwise.

        """
        try:
            self.sql_session.commit()
        except IntegrityError as error:
            self.application.service.add_notification(
                make_datetime(),
                "Operation failed.", "%s" % error)
            return False
        else:
            self.application.service.add_notification(
                make_datetime(),
                "Operation successful.", "")
            return True

    def safe_get_item(self, cls, ident, session=None):
        """Get item from database of class cls and id ident, using
        session if given, or self.sql_session if not given. If id is
        not found, raise a 404.

        cls (type): class of object to retrieve.
        ident (string): id of object.
        session (Session|None): session to use.

        return (object): the object with the given id.

        raise (HTTPError): 404 if not found.

        """
        if session is None:
            session = self.sql_session
        entity = cls.get_from_id(ident, session)
        if entity is None:
            raise tornado.web.HTTPError(404)
        return entity

    def prepare(self):
        """This method is executed at the beginning of each request.

        """
        # Attempt to update the contest and all its references
        # If this fails, the request terminates.
        self.set_header("Cache-Control", "no-cache, must-revalidate")

        self.sql_session = Session()
        self.sql_session.expire_all()
        self.contest = None

        if config.installed:
            localization_dir = os.path.join("/", "usr", "local", "share",
                                            "locale")
        else:
            localization_dir = os.path.join(os.path.dirname(__file__), "mo")
        if os.path.exists(localization_dir):
            tornado.locale.load_gettext_translations(localization_dir, "cms")

    def render_params(self):
        """Return the default render params used by almost all handlers.

        return (dict): default render params

        """
        params = {}
        params["timestamp"] = make_datetime()
        params["contest"] = self.contest
        params["url_root"] = get_url_root(self.request.path)
        if self.contest is not None:
            params["phase"] = self.contest.phase(params["timestamp"])
            # Keep "== None" in filter arguments. SQLAlchemy does not
            # understand "is None".
            params["unanswered"] = self.sql_session.query(Question)\
                .join(Participation)\
                .filter(Participation.contest_id == self.contest.id)\
                .filter(Question.reply_timestamp == None)\
                .filter(Question.ignored == False)\
                .count()  # noqa
        params["contest_list"] = self.sql_session.query(Contest).all()
        params["task_list"] = self.sql_session.query(Task).all()
        params["user_list"] = self.sql_session.query(User).all()
        return params

    def finish(self, *args, **kwds):
        """Finish this response, ending the HTTP request.

        We override this method in order to properly close the database.

        TODO - Now that we have greenlet support, this method could be
        refactored in terms of context manager or something like
        that. So far I'm leaving it to minimize changes.

        """
        self.sql_session.close()
        try:
            tornado.web.RequestHandler.finish(self, *args, **kwds)
        except IOError:
            # When the client closes the connection before we reply,
            # Tornado raises an IOError exception, that would pollute
            # our log with unnecessarily critical messages
            logger.debug("Connection closed before our reply.")

    def write_error(self, status_code, **kwargs):
        if "exc_info" in kwargs and \
                kwargs["exc_info"][0] != tornado.web.HTTPError:
            exc_info = kwargs["exc_info"]
            logger.error(
                "Uncaught exception (%r) while processing a request: %s",
                exc_info[1], ''.join(traceback.format_exception(*exc_info)))

        # Most of the handlers raise a 404 HTTP error before r_params
        # is defined. If r_params is not defined we try to define it
        # here, and if it fails we simply return a basic textual error notice.
        if self.r_params is None:
            try:
                self.r_params = self.render_params()
            except:
                self.write("A critical error has occurred :-(")
                self.finish()
                return
        self.render("error.html", status_code=status_code, **self.r_params)

    get_string = argument_reader(lambda a: a, empty="")

    # When a checkbox isn't active it's not sent at all, making it
    # impossible to distinguish between missing and False.
    def get_bool(self, dest, name):
        """Parse a boolean.

        dest (dict): a place to store the result.
        name (string): the name of the argument and of the item.

        """
        value = self.get_argument(name, False)
        try:
            dest[name] = bool(value)
        except:
            raise ValueError("Can't cast %s to bool." % value)

    get_int = argument_reader(parse_int)

    get_timedelta_sec = argument_reader(parse_timedelta_sec)

    get_timedelta_min = argument_reader(parse_timedelta_min)

    get_datetime = argument_reader(parse_datetime)

    get_ip_address_or_subnet = argument_reader(parse_ip_address_or_subnet)

    def get_submission_format(self, dest):
        """Parse the submission format.

        Using the two arguments "submission_format_choice" and
        "submission_format" set the "submission_format" item of the
        given dictionary.

        dest (dict): a place to store the result.

        """
        choice = self.get_argument("submission_format_choice", "other")
        if choice == "simple":
            filename = "%s.%%l" % dest["name"]
            format_ = [SubmissionFormatElement(filename)]
        elif choice == "other":
            value = self.get_argument("submission_format", "[]")
            if value == "":
                value = "[]"
            format_ = []
            try:
                for filename in json.loads(value):
                    format_ += [SubmissionFormatElement(filename)]
            except ValueError:
                raise ValueError("Submission format not recognized.")
        else:
            raise ValueError("Submission format not recognized.")
        dest["submission_format"] = format_

    def get_time_limit(self, dest, field):
        """Parse the time limit.

        Read the argument with the given name and use its value to set
        the "time_limit" item of the given dictionary.

        dest (dict): a place to store the result.
        field (string): the name of the argument to use.

        """
        value = self.get_argument(field, None)
        if value is None:
            return
        if value == "":
            dest["time_limit"] = None
        else:
            try:
                value = float(value)
            except:
                raise ValueError("Can't cast %s to float." % value)
            if not 0 <= value < float("+inf"):
                raise ValueError("Time limit out of range.")
            dest["time_limit"] = value

    def get_memory_limit(self, dest, field):
        """Parse the memory limit.

        Read the argument with the given name and use its value to set
        the "memory_limit" item of the given dictionary.

        dest (dict): a place to store the result.
        field (string): the name of the argument to use.

        """
        value = self.get_argument(field, None)
        if value is None:
            return
        if value == "":
            dest["memory_limit"] = None
        else:
            try:
                value = int(value)
            except:
                raise ValueError("Can't cast %s to float." % value)
            if not 0 < value:
                raise ValueError("Invalid memory limit.")
            dest["memory_limit"] = value

    def get_task_type(self, dest, name, params):
        """Parse the task type.

        Parse the arguments to get the task type and its parameters,
        and fill them in the "task_type" and "task_type_parameters"
        items of the given dictionary.

        dest (dict): a place to store the result.
        name (string): the name of the argument that holds the task
            type name.
        params (string): the prefix of the names of the arguments that
            hold the parameters.

        """
        name = self.get_argument(name, None)
        if name is None:
            raise ValueError("Task type not found.")
        try:
            class_ = get_task_type_class(name)
        except KeyError:
            raise ValueError("Task type not recognized: %s." % name)
        params = json.dumps(class_.parse_handler(self, params + name + "_"))
        dest["task_type"] = name
        dest["task_type_parameters"] = params

    def get_score_type(self, dest, name, params):
        """Parse the score type.

        Parse the arguments to get the score type and its parameters,
        and fill them in the "score_type" and "score_type_parameters"
        items of the given dictionary.

        dest (dict): a place to store the result.
        name (string): the name of the argument that holds the score
            type name.
        params (string): the name of the argument that hold the
            parameters.

        """
        name = self.get_argument(name, None)
        if name is None:
            raise ValueError("Score type not found.")
        try:
            get_score_type_class(name)
        except KeyError:
            raise ValueError("Score type not recognized: %s." % name)
        params = self.get_argument(params, None)
        if params is None:
            raise ValueError("Score type parameters not found.")
        dest["score_type"] = name
        dest["score_type_parameters"] = params


FileHandler = file_handler_gen(BaseHandler)


def SimpleHandler(page):
    class Cls(BaseHandler):
        def get(self):
            self.r_params = self.render_params()
            self.render(page, **self.r_params)
    return Cls


def SimpleContestHandler(page):
    class Cls(BaseHandler):
        def get(self, contest_id):
            self.contest = self.safe_get_item(Contest, contest_id)

            self.r_params = self.render_params()
            self.render(page, **self.r_params)
    return Cls


class ResourcesHandler(BaseHandler):
    def get(self, shard=None, contest_id=None):
        if contest_id is not None:
            self.contest = self.safe_get_item(Contest, contest_id)
            contest_address = "/%s" % contest_id
        else:
            contest_address = ""

        if shard is None:
            shard = "all"

        self.r_params = self.render_params()
        self.r_params["resource_shards"] = \
            get_service_shards("ResourceService")
        self.r_params["resource_addresses"] = {}
        if shard == "all":
            for i in range(self.r_params["resource_shards"]):
                self.r_params["resource_addresses"][i] = get_service_address(
                    ServiceCoord("ResourceService", i)).ip
        else:
            shard = int(shard)
            try:
                address = get_service_address(
                    ServiceCoord("ResourceService", shard))
            except KeyError:
                self.redirect("/resourceslist%s" % contest_address)
                return
            self.r_params["resource_addresses"][shard] = address.ip

        self.render("resources.html", **self.r_params)


class NotificationsHandler(BaseHandler):
    """Displays notifications.

    """
    def get(self):
        res = []
        last_notification = make_datetime(
            float(self.get_argument("last_notification", "0")))

        # Keep "== None" in filter arguments. SQLAlchemy does not
        # understand "is None".
        questions = self.sql_session.query(Question)\
            .filter(Question.reply_timestamp == None)\
            .filter(Question.question_timestamp > last_notification)\
            .all()  # noqa

        for question in questions:
            res.append({
                "type": "new_question",
                "timestamp": make_timestamp(question.question_timestamp),
                "subject": question.subject,
                "text": question.text,
                "contest_id": question.participation.contest_id
            })

        # Simple notifications
        for notification in self.application.service.notifications:
            res.append({"type": "notification",
                        "timestamp": make_timestamp(notification[0]),
                        "subject": notification[1],
                        "text": notification[2]})
        self.application.service.notifications = []

        self.write(json.dumps(res))