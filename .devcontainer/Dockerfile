FROM mcr.microsoft.com/devcontainers/python:3.13

# Fix Yarn GPG issue - remove Yarn repository before apt-get update
RUN rm -f /etc/apt/sources.list.d/yarn.list && apt-get update
