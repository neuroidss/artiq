#!/usr/bin/env python3

import argparse

from artiq.devices.lda.driver import Lda, Ldasim
from artiq.protocols.pc_rpc import simple_server_loop
from artiq.tools import verbosity_args, init_logger


def get_argparser():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', default="LDA-102",
                        choices=["LDA-102", "LDA-602", "sim"])
    parser.add_argument('--bind', default="::1",
                        help="hostname or IP address to bind to")
    parser.add_argument('-p', '--port', default=3253, type=int,
                        help="TCP port to listen to")
    parser.add_argument('-s', '--serial', default=None,
                        help="USB serial number of the device")
    verbosity_args(parser)
    return parser


def main():
    args = get_argparser().parse_args()
    init_logger(args)
    if args.device == "sim":
        lda = Ldasim()
    else:
        lda = Lda(args.serial, args.device)
    simple_server_loop({"lda": lda},
                       args.bind, args.port)

if __name__ == "__main__":
    main()
