#! /usr/bin/env python3
# This file is part of Dataloop

from setuptools import setup, find_packages
import pathlib
import os

with open('README.md') as f:
    readme = f.read()

with open('requirements.txt') as f:
    requirements = f.read()

packages = [
    package for package in find_packages() if package.startswith("dataloop")
]

setup(name='dataloop-converter',
      classifiers=[
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
          'Programming Language :: Python :: 3.9',
      ],
      version='0.2.0',
      description='Converter for Dataloop annotations format',
      author='Dataloop Team',
      author_email='info@dataloop.ai',
      long_description=readme,
      long_description_content_type='text/markdown',
      packages=find_packages(),
      setup_requires=['wheel'],
      install_requires=requirements,
      python_requires='>=3.7',
      include_package_data=True,
      )
