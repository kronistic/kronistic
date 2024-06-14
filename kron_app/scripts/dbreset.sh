#!/bin/bash
set -e
psql postgres -c "create database kron;"
python -c "from kron_app import db; db.create_all()"
