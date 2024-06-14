import json
import traceback
from flask import render_template, request
from flask_login import current_user
from kron_app import app, db
from kron_app.models import ErrorLog

@app.errorhandler(404)
def not_found_error(error):
  return render_template('404.html'), 404

@app.errorhandler(400)
@app.errorhandler(500)
def internal_error(error):
  db.session.rollback()
  exception = error.original_exception
  #tb = ''.join(traceback.format_tb(exception.__traceback__))
  tb = ''.join(traceback.format_exception(None, exception, tb=exception.__traceback__))
  e = ErrorLog()
  e.data = dict(src='web',
                detail=dict(url=request.url,
                            method=request.method,
                            formdata=request.form,
                            user_id=current_user.id if current_user.is_authenticated else None),
                exception=type(exception).__name__,
                tb=tb)
  db.session.add(e)
  db.session.commit()
  return render_template('500.html'), 500
