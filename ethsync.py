# Indexer for Ethereum to get transaction list by ETH address
# https://github.com/Adamant-im/ETH-transactions-storage

# Contributions:
# 2021-2022 ADAMANT Foundation (devs@adamant.im), Francesco Bonanno (mibofra@parrotsec.org),
# Guénolé de Cadoudal (guenoledc@yahoo.fr), Drew Wells (drew.wells00@gmail.com)
# 2020-2021 ADAMANT Foundation (devs@adamant.im): Aleksei Lebedev
# 2017-2020 ADAMANT TECH LABS LP (pr@adamant.im): Artem Brunov, Aleksei Lebedev
# v2.1

from os import environ
from web3 import Web3, AsyncHTTPProvider, AsyncWeb3
from web3.middleware import geth_poa_middleware
from urllib.parse import urlparse

import asyncio
import psycopg2
import time
import logging
# from systemd.journal import JournalHandler

# Get env variables or set to default
postgres_uri = environ.get("POSTGRES_URI")
startBlock = environ.get("START_BLOCK") or "1"
confirmationBlocks = environ.get("CONFIRMATIONS_BLOCK") or "0"
nodeUrl = environ.get("ETH_URL")
pollingPeriod = environ.get("PERIOD") or "20"
logFile = environ.get("LOG_FILE")

if postgres_uri == None:
    print('Add postgre database in env var POSTGRES_URI')
    exit(2)

if nodeUrl == None:
    print('Add eth url in env var ETH_URL')
    exit(2)

# Connect to Ethereum node
if not nodeUrl.startswith("http"):
    print('Only HTTP supported')
    exit(1)

web3 = Web3(Web3.HTTPProvider(nodeUrl))  # "http://publicnode:8545"
asyncWeb3 = AsyncWeb3(AsyncHTTPProvider(nodeUrl))  # "http://publicnode:8545"

web3.middleware_onion.inject(geth_poa_middleware, layer=0)

# Start logger
# logger = logging.getLogger("EthIndexerLog")
logger = logging.getLogger("eth-sync")
logger.setLevel(logging.INFO)

# File logger
if logFile == None:
    lfh = logging.StreamHandler()
else:
    lfh = logging.FileHandler(logFile)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
lfh.setFormatter(formatter)
logger.addHandler(lfh)

# Systemd logger, if we want to user journalctl logs
# Install systemd-python and
# decomment "#from systemd.journal import JournalHandler" up
# ljc = JournalHandler()
# formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
# ljc.setFormatter(formatter)
# logger.addHandler(ljc)

connected = False

for i in range(10, 0, -1):
    try:
        logger.info("Trying to connect to " + postgres_uri + " database…")

        result = urlparse(postgres_uri)
        username = result.username
        password = result.password
        database = result.path[1:]
        hostname = result.hostname
        port = result.port

        conn = psycopg2.connect(
            database=database,
            user=username,
            password=password,
            host=hostname,
            port=port
        )

        conn.autocommit = True
        logger.info("Connected to the database")
        connected = True
        break

    except Exception as e:
        logger.error("Error while connecting", str(e))
        logger.error("Retrying to connect... attempts: " + str(i))
        time.sleep(2)

if not connected:
    logger.error("Unable to connect to database")
    exit(1)

# Delete last block as it may be not imported in full
cur = conn.cursor()
cur.execute(
    'DELETE FROM public.ethtxs WHERE block = (SELECT Max(block) from public.ethtxs)')
cur.close()
conn.close()

# Wait for the node to be in sync before indexing
while web3.eth.syncing != False:
    # Change with the time, in second, do you want to wait
    # before checking again, default is 5 minutes
    logger.info("Waiting Ethereum node to be in sync…")
    time.sleep(300)

logger.info("Ethereum node is synced.")

# Adds all transactions from Ethereum block


def insertTxsFromBlock(block):
    blockid = block['number']
    time = block['timestamp']

    transaction_receipts = [None for i in range(0, len(block.transactions))]

    async def handler():
        for result in asyncio.as_completed([asyncWeb3.eth.get_transaction_receipt(block.transactions[i]['hash']) for i in range(0, len(block.transactions))]):
            transReceipt = await result
            txNumber = transReceipt['transactionIndex']
            transaction_receipts[txNumber] = transReceipt

    asyncio.run(handler())

    for txNumber in range(0, len(block.transactions)):
        trans = block.transactions[txNumber]
        transReceipt = transaction_receipts[txNumber]
        # Save also transaction status, should be null if pre byzantium blocks
        status = bool(transReceipt['status'])
        txhash = trans['hash'].hex()
        value = trans['value']
        inputinfo = trans['input'].hex()
        fr = trans['from']
        to = trans['to'] if 'to' in trans else None
        # If contract is created, make sure
        if to is None:
            contractAddress = transReceipt['contractAddress']
            if contractAddress is not None:
                to = contractAddress
        cur.execute(
            'INSERT INTO public.ethtxs(time, txfrom, txto, value, block, txhash, input, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (time, fr, to, value, blockid, txhash, inputinfo, status)
        )


# Fetch all of new (not in index) Ethereum blocks and add transactions to index
while True:
    try:
        result = urlparse(postgres_uri)
        username = result.username
        password = result.password
        database = result.path[1:]
        hostname = result.hostname
        port = result.port

        conn = psycopg2.connect(
            database=database,
            user=username,
            password=password,
            host=hostname,
            port=port
        )
        conn.autocommit = True
    except:
        logger.error("Unable to connect to database")

    cur = conn.cursor()

    cur.execute('SELECT Max(block) from public.ethtxs')
    maxblockindb = cur.fetchone()[0]
    # On first start, we index transactions from a block number you indicate
    if maxblockindb is None:
        maxblockindb = int(startBlock)

    endblock = int(web3.eth.block_number) - int(confirmationBlocks)

    logger.info('Current best block in index: ' +
                str(maxblockindb) + '; in Ethereum chain: ' + str(endblock))

    for blockHeight in range(maxblockindb + 1, endblock):
        block = web3.eth.get_block(blockHeight, True)
        if len(block.transactions) > 0:
            insertTxsFromBlock(block)
            logger.info('Block ' + str(blockHeight) + ' with ' +
                        str(len(block.transactions)) + ' transactions is processed')
        else:
            logger.info('Block ' + str(blockHeight) +
                        ' does not contain transactions')
    cur.close()
    conn.close()
    time.sleep(int(pollingPeriod))
