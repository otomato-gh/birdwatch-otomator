FROM otomato/python-k8s-client
LABEL "MAINTAINER"="Otomato Software Ltd. <contact@otomato.link>"
ADD controller.py /birdwatch
ADD guitar.yml /birdwatch

ENTRYPOINT  ["python", "-u", "/birdwatch/controller.py"]
