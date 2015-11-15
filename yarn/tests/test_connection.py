#!/usr/bin/env python

import os
import getpass
import unittest
from yarn.api import env, run, local

env.host_string = local('ifconfig eth0 | grep "inet addr" | cut -d":" -f2 | awk \'{print $1}\'')
env.host_port = 2222
env.password = "123456"

class TestConnection(unittest.TestCase):

    def test_simple_connection(self):
        print(env.__dict__)
        run("uptime")

    
