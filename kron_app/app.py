import os
from os.path import join
from kron_app import app
basedir = os.path.abspath(os.path.dirname(__file__))

if __name__ == "__main__":
  ssl_dir = join(basedir, 'src/app/ssl')
  app.run(
    # To test error logging locally set `debug=False`, `use_debugger=False`.
    debug=True,
    ssl_context=(
      join(basedir, 'ssl/ssl.crt'), 
      join(basedir, 'ssl/ssl.key')),
    host='localhost',
    port='8080')
