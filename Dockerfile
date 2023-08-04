FROM python:3.11.4-slim

RUN apt update -y
RUN apt install -y build-essential libpq-dev
RUN apt install -y git
RUN pip3 install --upgrade pip
RUN pip3 install web3==6.8.0
RUN pip3 install psycopg2==2.9.6

RUN mkdir /eth-storage

COPY ./ethsync.py /eth-storage

WORKDIR /eth-storage
ENTRYPOINT [ "python3.11", "./ethsync.py" ]
