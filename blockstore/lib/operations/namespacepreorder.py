#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Blockstore
    ~~~~~
    copyright: (c) 2014 by Halfmoon Labs, Inc.
    copyright: (c) 2015 by Blockstack.org
    
    This file is part of Blockstore
    
    Blockstore is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    
    Blockstore is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with Blockstore.  If not, see <http://www.gnu.org/licenses/>.
"""

from pybitcoin import embed_data_in_blockchain, \
    analyze_private_key, serialize_sign_and_broadcast, make_op_return_script, \
    make_pay_to_address_script, b58check_encode, b58check_decode, BlockchainInfoClient, hex_hash160

from pybitcoin.transactions.outputs import calculate_change_amount

from utilitybelt import is_hex
from binascii import hexlify, unhexlify

from ..b40 import b40_to_hex, bin_to_b40, is_b40
from ..config import *
from ..scripts import blockstore_script_to_hex, add_magic_bytes, get_script_pubkey
from ..hashing import hash_name

def build( namespace_id, script_pubkey, register_addr, consensus_hash, testset=False ):
   """
   Preorder a namespace with the given consensus hash.  This records that someone has begun to create 
   a namespace, while blinding all other peers to its ID.  This operation additionally records the 
   consensus hash in order to ensure that all peers will recognize that this sender has begun the creation.
   
   Takes an ASCII-encoded namespace ID.
   NOTE: "namespace_id" must not start with ., but can contain anything else we want
   
   We put the hash of the namespace ID instead of the namespace ID itself to avoid races with squatters (akin to pre-ordering)
   
   Format:
   
   0     2   3                                      23               39
   |-----|---|--------------------------------------|----------------|
   magic op  hash(ns_id,script_pubkey,register_addr) consensus hash
   """
   
   # sanity check 
   if not is_b40( namespace_id ) or "+" in namespace_id or namespace_id.count(".") > 0:
      raise Exception("Namespace identifier '%s' has non-base-38 characters" % namespace_id)
   
   if len(namespace_id) == 0 or len(namespace_id) > LENGTHS['blockchain_id_namespace_id']:
      raise Exception("Invalid namespace ID length '%s (expected length between 1 and %s)" % (namespace_id, LENGTHS['blockchain_id_namespace_id']))
   
   namespace_id_hash = hash_name(namespace_id, script_pubkey, register_addr=register_addr)
   
   readable_script = "NAMESPACE_PREORDER 0x%s 0x%s" % (namespace_id_hash, consensus_hash)
   hex_script = blockstore_script_to_hex(readable_script)
   packaged_script = add_magic_bytes(hex_script, testset=testset)
   
   return packaged_script


def make_outputs( data, inputs, change_addr, fee, format='bin' ):
    """
    Make outputs for a namespace preorder:
    [0] OP_RETURN with the name 
    [1] change address with the NAME_PREORDER sender's address
    [2] pay-to-address with the *burn address* with the fee
    """
    
    total_to_send = DEFAULT_OP_RETURN_FEE + DEFAULT_DUST_FEE + max(fee, DEFAULT_DUST_FEE)
    
    return [
        # main output
        {"script_hex": make_op_return_script(data, format=format),
         "value": DEFAULT_OP_RETURN_FEE},
        
        # change address
        {"script_hex": make_pay_to_address_script(change_addr),
         "value": calculate_change_amount(inputs, total_to_send, (len(inputs) + 3) * DEFAULT_DUST_FEE)},
        
        # burn address
        {"script_hex": make_pay_to_address_script(BLOCKSTORE_BURN_ADDRESS),
         "value": max(fee, DEFAULT_DUST_FEE)}
    ]
    

def broadcast( namespace_id, register_addr, consensus_hash, private_key, blockchain_client, fee, testset=False ):
   """
   Propagate a namespace.
   
   Arguments:
   namespace_id         human-readable (i.e. base-40) name of the namespace
   register_addr        the addr of the key that will reveal the namespace (mixed into the preorder to prevent name preimage attack races)
   private_key          the Bitcoin address that created this namespace, and can populate it.
   """
    
   script_pubkey = get_script_pubkey( private_key )
   nulldata = build( namespace_id, script_pubkey, register_addr, consensus_hash, testset=testset )
   
   # get inputs and from address
   private_key_obj, from_address, inputs = analyze_private_key(private_key, blockchain_client)
    
   # build custom outputs here
   outputs = make_outputs(nulldata, inputs, from_address, fee, format='hex')
    
   # serialize, sign, and broadcast the tx
   response = serialize_sign_and_broadcast(inputs, outputs, private_key_obj, blockchain_client)
    
   # response = {'success': True }
   response.update({'data': nulldata})
    
   return response
   

def parse( bin_payload ):
   """
   NOTE: the first three bytes will be missing
   """
   
   namespace_id_hash = bin_payload[ :LENGTHS['preorder_name_hash'] ]
   consensus_hash = bin_payload[ LENGTHS['preorder_name_hash']: LENGTHS['preorder_name_hash'] + LENGTHS['consensus_hash'] ]
   
   namespace_id_hash = hexlify( namespace_id_hash )
   consensus_hash = hexlify( consensus_hash )
   
   return {
      'opcode': 'NAMESPACE_PREORDER',
      'namespace_id_hash': namespace_id_hash,
      'consensus_hash': consensus_hash
   }


def serialize( nameop ):
    """
    Convert the set of data obtained from parsing the namespace preorder into a unique string.
    """
    
    return NAMESPACE_PREORDER + ":" + nameop['namespace_id_hash'] + "," + nameop['consensus_hash']
