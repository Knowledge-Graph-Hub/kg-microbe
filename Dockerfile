# Get Ubunto 20.04 image
FROM ubuntu:20.04 

# Setup OS with Python and other tools
RUN apt-get update &&\
    apt-get -y install git &&\
    apt-get -y install python3 &&\
    apt-get -y install python3-pip

# Declare workspace directory
WORKDIR /usr/src/app

# Copy all files in the workspace directory
COPY . .

# KG-Microbe setup
RUN python3 setup.py install &&\
    pip3 install --no-cache-dir -r requirements.txt &&\
    python3 run.py download &&\
    python3 run.py transform &&\
    python3 run.py merge

# Provision to use the Docker container using terminal
CMD /bin/bash