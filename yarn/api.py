import os
import sys
import logging
import paramiko
import subprocess
import multiprocessing
if sys.version_info.major == 2:
    from environment import Environment
else:
    from yarn.environment import Environment
from getpass import getpass
from contextlib import contextmanager
from paramiko.ssh_exception import AuthenticationException, SSHException


logger = logging.getLogger("Yarn")
logger.setLevel(logging.DEBUG)
# I really, really wish I could change the format of this to have my
# connection_string in it, but I am unwilling to break the logger to do it.
# logging.basicConfig(format='[%(asctime)s] %(levelname)s - %(funcName)s: %(message)s')


# Here is the global environment for the system.  Pretty much everyone will
# use this.
env = Environment()
env.quiet=False

class ConnectionStringFilter(logging.Filter):
    def filter(self, record):
        record.connection_string = env.connection_string
        return True


logging.basicConfig(format='[%(connection_string)s] %(levelname)s: %(message)s')
logger.addFilter(ConnectionStringFilter())

def handle_output(stdout, stderr):
    try:
        stdout = [a.decode('utf-8').strip() for a in stdout.read().splitlines() if a]
        stderr = [a.decode('utf-8').strip() for a in stderr.read().splitlines() if a]
    except AttributeError:
        stdout = [a.decode('utf-8').strip() for a in stdout.splitlines() if a]
        stderr = [a.decode('utf-8').strip() for a in stderr.splitlines() if a]

    if not stderr:
        for a in stdout:
            logging.info(a)
        return "\n".join(stdout)
    if not env.quiet:
        logging.warning("\n".join(stderr))
        logging.warning("ENV_DEBUG: '{}'".format(local("env")))
    if not env.warn_only:
        sys.exit(1)

# Starting the work for local execution per GitHub Issue #20
def local(command):
    proc = subprocess.Popen(command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    return handle_output(stdout, stderr)

# Starting the work for sudo per GitHub Issue #20
def sudo(command):
    if not env.password:
        env.password = getpass("Password for {}: ".format(env.connection_string))
    return run(command='sudo -Si {}'.format(command))

# The joys of running in parallel
def parallel(wrapped_function):
    def _wrapped(*args, **kwargs):
        if env.run_parallel:
            task = multiprocessing.Process(target=wrapped_function, args=args, kwargs=kwargs)
            env.parallel_tasks.append(task)
            task.start()
        else:
            return wrapped_function(*args, **kwargs)
    return _wrapped


# This might be somewhat important.
def ssh_connection(wrapped_function):
    logger.debug("Creating SSH connection")

    def _wrapped(*args, **kwargs):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if env.key is not None and env._paramiko_key is None:
            env._paramiko_key = paramiko.RSAKey.from_private_key(open(env.key), password=env.passphrase)
        if not env.host_string:
            env.host_string = input("No hosts were specified.  Host IP/DNS Name: ")
        try:
            # Here is where the conncetion is setup.
            ssh.connect(env.host_string, env.host_port, username=env.user,
                        pkey=env._paramiko_key)
            return wrapped_function(*args, conn=ssh, **kwargs)
        except (SSHException, AuthenticationException):
            # If there is a problem with the pervious attempt (no/bad password)
            # Here is where we will query for it and try again.
            if not env.password:
                env.password = getpass("Password for {}: ".format(env.connection_string))
            ssh.connect(env.host_string, env.host_port, username=env.user,
                        password=env.password)
            return wrapped_function(*args, conn=ssh, **kwargs)
        finally:
            # Gotta love the cleanup associated with the finally call in Python.
            logger.debug("Closing connection")
            ssh.close()

    return _wrapped


def environment_builder(wrapped_function):
    def _wrapped(*args, **kwargs):
        if 'quiet' in kwargs:
            env.quiet = kwargs.pop('quiet')
        if 'warn_only' in kwargs:
            env.warn_only = kwargs.pop('warn_only')
        if 'pty' in kwargs:
            env.pty = kwargs.pop('pty')
        return wrapped_function(*args, **kwargs)
    return _wrapped


@contextmanager
@environment_builder
def settings(**kwargs):
    yield


@contextmanager
def cd(path):
    # Yes, I know it's simplistic.  But if it's stupid and it works, then it
    # ain't stupid.
    try:
        env.working_directory.append(path)
        yield
        env.working_directory.pop()
    except TypeError:
        raise TypeError("In order to use the CD context manager, you must specify a path string")


# The meat and potatoes of the entire system.
def run(command, **kwargs):
    @environment_builder
    @ssh_connection
    def run_command(*args, **kwargs):
        command = kwargs['command']
        if env.working_directory:
            command = "cd {} && {}".format(" && cd ".join(env.working_directory), command)
        conn = kwargs['conn']
        if not env.quiet:
            logger.debug("'{}'".format(command))
        if "sudo" in command:
            stdin, stdout, stderr = conn.exec_command(command, get_pty=True, timeout=30)
            output_buffer = ""
            while not '[sudo]' in output_buffer:
                output_buffer += stdout.channel.recv(2048).decode('utf-8')
            stdin.write('{}\n'.format(env.password))
            stdin.flush()
        else:
            stdin, stdout, stderr = conn.exec_command(command, timeout=30)
        return handle_output(stdout, stderr)
    return run_command(command=command, **kwargs)


# Putting a file is handy.  I may decide to check and see if there is already
# an identical file in place so that we don't copy the same file over and over
# again.  Hmmmm....
def put(local_path, remote_path):
    @ssh_connection
    def put_file(*args, **kwargs):
        ssh = kwargs['conn']
        local_path = kwargs['local_path']
        remote_path = kwargs['remote_path']
        logger.debug("Uploading {} to {}:{}".format(
                    local_path, env.connection_string, remote_path))
        ftp = ssh.open_sftp()
        ftp.put(local_path, remote_path)
        ftp.close()
    return put_file(local_path=local_path, remote_path=remote_path)


# Getting a file is nifty.
def get(remote_path, local_path=None):
    @ssh_connection
    def get_file(*args, **kwargs):
        ssh = kwargs['conn']
        remote_path = kwargs['remote_path']
        local_path = kwargs['local_path']
        logger.debug("Downloading {}:{}.  Placing it: {}".format(
                        env.connection_string, remote_path, local_path))
        ftp = ssh.open_sftp()
        ftp.get(remote_path, local_path)
        ftp.close()
    if not local_path:
        local_path = os.path.join(local_path, os.path.split(remote_path)[-1])
    return get_file(remote_path=remote_path, local_path=local_path)
