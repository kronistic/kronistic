# Set-up for local dev

- Install Python 3.8
  - The project was originally written for Python 3.8. Other versions
    may work, but are untested.
- `git clone` the [repo](https://github.com/kronistic/kronistic)
- Consider making a [venv](https://docs.python.org/3/library/venv.html) for the project
- Install the `kronistic` package (in editable mode)
  - `cd kronistic`
  - `pip install -r requirements.txt`
  - `pip install -e .[dev]`
- Install postgres
- Create database `kron`
  - `psql postgres -c "create database kron;"`
- Set the following environment variables if the web app needs to use
  something other than the default username and password to connect to
  postgres. This probably isn't necessary with a default postgres
  install.
  - `export POSTGRES_USERNAME=<user>`
  - `export POSTGRES_PASSWORD=<pass>`
- SSL set-up: Open a python repl and issue the following commands to
  make local dev certs. Move the generated `ssl.crt` and `ssl.key` to
  directory `kron_app/ssl`
  - `from werkzeug.serving import make_ssl_devcert`
  - `make_ssl_devcert('./ssl', host='localhost')`
- Run migrations to create db tables:
  - `cd kron_app`
  - `flask db upgrade`
- Google API set-up:
  - Visit [Google API console](https://console.developers.google.com/)
  - Create project:
    - Click "Create Project", and complete that form using e.g.
      "kron-local" as the name.
    - (When existing projects are present, click the project drop-down
      in the header and choose "New Project" instead.)
  - Configure consent screen:
    - Choose "OAuth consent screen" from the left nav
    - Choose "External" for "User Type"
    - Go through wizard:
      - Step 1: Nothing critical here, and a lot of fields are
        optional. I again used "kron-local" for the name.
      - Step 2 (Scopes): Do "Add or Remove Scopes". Copy and paste
        `https://www.googleapis.com/auth/calendar` into "Manually
        added scopes", and click "Add to table". Then select
        `auth/userinfo.email`, `auth/userinfo.profile`,
        `auth/calendar` from the list, and click "Update".
      - Step 3: Add yourself as a test user.
  - Enable the calendar API:
    - Choose "Library" from the left nav
    - Search for "calendar"
    - Choose "Google Calendar API"
    - Click "Enable"
  - Create OAuth credentials to support user login:
    - Choose "Credentials" from the left nav, then "Create
      Credentials", then "OAuth client ID".
    - Complete the form:
      - Application type "Web application"
      - Name e.g. "kron-dev" (the specific name used is not important)
      - "Authorised JavaScript origins": `https://localhost:8080`
      - "Authorised redirect URIs": `https://localhost:8080/gCallback`
    - Export the generated client ID and secret as
      `KRON_GOOGLE_OAUTH2_ID` and `KRON_GOOGLE_OAUTH2_SECRET` env vars
- Optional OpenAI API set-up:
  - Add API key as `OPENAI_API_KEY` env var.

# Running the app locally

- Ensure postgres is running
- Run the web server: `cd kron_app`, `python app.py`
  - The app is available at `https://localhost:8080`
- Start a task queue worker process with:
  - `celery -A kron_app.tasks worker -c 1 --loglevel=INFO -B`
- Google calendar push notifications:
  - Set-up a secure tunnel to make local web server available via the
    public internet over https. (Using
    e.g. [ngrok](https://ngrok.com/).)
  - Set the env var `GCAL_WEBHOOK_HOST` to be the hostname of the
    tunnel.
