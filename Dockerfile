FROM python:3

WORKDIR /usr/src/app
COPY . .
RUN python setup.py install
RUN pip install --no-cache-dir -r requirements.txt
RUN python run.py download
RUN python run.py transform
RUN python run.py merge
CMD /bin/bash