FROM python:3.8

ADD . /app
WORKDIR /app

RUN /usr/local/bin/python -m pip install --upgrade pip
RUN pip install -r requirements.txt
ENTRYPOINT ["python3", "main.py"]
