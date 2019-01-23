# Image from https://hub.docker.com (syntax: repo/image:version)
FROM continuumio/miniconda3:4.5.12

# Person responsible
MAINTAINER helge.dzierzon@brockmann-consult.de

LABEL name=xcube-server
LABEL version=0.1.0
LABEL conda_env=xcube-server-dev

# Ensure usage of bash (simplifies source activate calls)
SHELL ["/bin/bash", "-c"]

# Update system and install dependencies
RUN apt-get -y update && apt-get -y upgrade

# && apt-get -y install  git build-essential libyaml-cpp-dev

# Setup conda environment
# Copy yml config into image
ADD environment.yml /tmp/environment.yml

# Update conda and install dependecies specified in environment.yml
RUN  conda env create -f=/tmp/environment.yml;

# Set work directory for xcube server installation
RUN mkdir /xcube-server ; mkdir /EOdata
WORKDIR /xcube-server

# Copy local github repo into image (will be replaced by either git clone or as a conda dep)
ADD . /xcube-server

# Setup eocdb-dev
RUN source activate xcube-server-dev && python setup.py develop

# Test eocdb-dev
ENV NUMBA_DISABLE_JIT 1
  # Uncomment following line if web testing on travis breaks our build
ENV CATE_DISABLE_WEB_TESTS 1
ENV CATE_DISABLE_PLOT_TESTS 1
ENV CATE_DISABLE_CLI_UPDATE_TESTS 1
# RUN source activate xcube-server-dev && pytest --cov=xcube

# Export web server port 4000
EXPOSE 8083

# Start server

ENTRYPOINT ["/bin/bash", "-c"]
CMD ["source activate xcube-server-dev && xcube-server -n 'cyanoalert-dev' -p 8083 -a '0.0.0.0' -u 30 -c 'server-config.yml' ]
