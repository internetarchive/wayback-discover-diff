from setuptools import setup, find_packages

setup(
    name='wayback-discover-diff',
    version='0.1.6.15',
    description='Calculate wayback machine captures simhash',
    packages=find_packages(),
    zip_safe=False,
    install_requires=[
        'Flask',
        'simhash',
        'redis',
        'urllib3',
        'PyYAML',
        'Celery',
        'lxml',
        'beautifulsoup4',
        'flask-cors',
        'surt'
        ],
    tests_require=[
        'pytest',
        'mock',
        'pylint'
        ],
    )
