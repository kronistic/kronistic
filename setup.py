from setuptools import setup

setup(
    name='kronistic',
    packages=['kron_app'],
    include_package_data=True,
    install_requires=[
        'flask',
        'SQLAlchemy',
        'Flask-SQLAlchemy',
        'Flask-Migrate',
        'flask-login',
        'flask-bootstrap',
        'requests-oauthlib',
        'Flask-WTF[email]',
        'cryptography',
        'psycopg2-binary',
        'python-dateutil',
        'celery',
        'z3-solver',
        'pysmt',
        'pydantic',
        'pandas',
        'lark',
        'psutil',
        'openai',
        'retry',
    ],
    extras_require={
        'dev': [
            'pytest',
            'sqlalchemy-utils',
        ],
    },
)
