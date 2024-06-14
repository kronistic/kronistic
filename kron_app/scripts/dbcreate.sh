#!/bin/bash
set -e
psql postgres -c "create database kron;"
cd $(dirname "$0")/..
flask db upgrade
