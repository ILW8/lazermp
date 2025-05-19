FROM python:3.11

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./main.py /code/
COPY ./templates /code/templates
COPY ./static /code/static

CMD ["fastapi", "run", "main.py", "--proxy-headers", "--port", "80"]