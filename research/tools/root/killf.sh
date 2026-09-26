#!/bin/sh
for p in $(ps -eo pid,args | grep "[p]ython field" | awk '{print $1}'); do kill $p; done
