#!/usr/bin/env python

import os
import getpass
import unittest
from yarn.api import env, run

env.host_string = "127.0.0.1"
env.host_port = 2222
env.password = "123456"

class TestConnection(unittest.TestCase):

    def test_simple_connection(self):
        run("uptime")

    
