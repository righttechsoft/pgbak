import logging
import os
import sys

logger = logging.getLogger('my_logger_name')


class SingleInstance:
  """If you want to prevent your script from running in parallel just create
  SingleInstance() object.
  Example of usage:
  >>> my_unique_process_name = 'example-proc-1'
  >>> me = SingleInstance(my_unique_process_name)
  Tribute for tendo (https://github.com/pycontribs/tendo).
  """

  def __init__(self, process_name):

    self.lock_file = '/tmp/{}.lock'.format(process_name)

    if sys.platform == 'win32':
      try:
        # File already exists, we try to remove (in case previous execution was
        # interrupted)
        if os.path.exists(self.lock_file):
          os.unlink(self.lock_file)
        self.fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
      except OSError as e:
        if e.errno == 13:
          logger.debug("Another instance is already running ({}), quitting.".
                       format(self.lock_file))
          sys.exit(-1)
        logger.debug(e.errno)
        raise

    else:  # non Windows
      import fcntl

      self.fp = open(self.lock_file, 'w')
      try:
        fcntl.lockf(self.fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except IOError:
        logger.debug("Another instance is already running ({}), quitting.".
                     format(self.lock_file))
        sys.exit(-1)

  def __del__(self):
    if sys.platform == 'win32':
      if hasattr(self, 'fd'):
        os.close(self.fd)
        os.unlink(self.lock_file)