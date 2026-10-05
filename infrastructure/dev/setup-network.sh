#!/usr/bin/env bash

# Cria a rede externa caso não exista
if ! docker network ls | grep -q "smarkee-dev-network"; then
  echo "Criando rede smarkee-dev-network..."
  docker network create smarkee-dev-network
else
  echo "Rede smarkee-dev-network já existe."
fi
