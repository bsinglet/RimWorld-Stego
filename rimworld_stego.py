"""
 Filename: rimworld_stego.py
 Description: Utility for concealing data in the save files of the popular game RimWorld.
 Created by: Benjamin M. Singleton
 Created: 03-09-2018
 Modified: 04-02-2018

 Improvements:
 -Better whitespace mixing
 -Fix argparser code
"""
from lxml import etree
from decimal import Decimal
import argparse
import math
import sys
import re


def load_savefile(filename):
    # return xml.etree.ElementTree.parse(filename).getroot()
    with open(filename) as f:
        # tree = etree.fromstring(f)
        s = f.read()
    s = s.replace('\n', '').replace('\t', '')
    tree = etree.fromstring(s)
    return tree


def find_grass_elements(root):
    """
    Given an ElementTree of a RimWorld save file, find all of the PlantGrass
    and PlantTallGrass things.
    :param root: The XML tree of the save file.
    :type root: lxml.ElementTree
    :return: The list of found things.
    :rtype: list
    """
    things = root.xpath('/savegame/game/maps/li/things')[0]
    elements = list()
    for each in things:
        if each.get('Class') == 'Plant' and each[0].text in ['PlantGrass', 'PlantTallGrass']:
            elements.append(each)
    return elements


def set_grass_bits(element, bits, bit_index):
    """
    Given a PlantGrass or PlantTallGrass element, encode
    bits[bit_index:bit_index+70] in its various fields.
    :param element: The element to conceal the data in.
    :type element: lxml.Element
    :param bits: The string of raw bits used for the entire operation.
    :type bits: str
    :param bit_index: The starting index in bits to read from.
    :type bit_index: int
    :return: The final value of bit_index, which is either 50 or 70 higher
    than what was passed to the function.
    :rtype: int
    """
    if len(bits[bit_index:]) < 70:
        bits += '0' * int((math.ceil(len(bits[bit_index:]) / 70.0) * 70) - len(bits[bit_index:]))
    # the id holds 18 bits of data (e.g., 'PlantGrass0256' = 256)
    id = int(bits[bit_index:bit_index + 18], 2)
    prefix = element[0].text  # either 'PlantGrass' or 'PlantTallGrass'
    element[1].text = prefix + str(id)
    bit_index += 18
    # health is an integer between 5 and 85, holding 6 bits of our data
    health = int(bits[bit_index:bit_index + 6], 2) + 5
    element[4].text = str(health)
    bit_index += 6
    # we know growth can have at least 8 decimal digits in the fractional
    # part, so we're storing 26 bits in here
    growth = Decimal(int(bits[bit_index:bit_index + 26], 2)) / Decimal(100000000)
    element[5].text = str(growth)
    bit_index += 26
    # we know age can go at least as high as 1,096,000, so we're storing 20 bits here
    age = int(bits[bit_index:bit_index + 20], 2)
    try:  # age isn't always present
        element[6].text = str(age)
        bit_index += 20
    except:
        # if not, no real loss
        pass
    return bit_index


def bytes_to_grasses(elements, bytes):
    """
    Given a list of PlantGrass and PlantTallGrass elements and a string of
    bits, encode the data in the elements.
    :param elements: The list of elements to hide data in.
    :type elements: lxml.Element
    :param bytes: The list of bytes to encode.
    :type bits: list
    :return: Nothing.
    """
    # turn the list of bytes into a string of bits
    bits = ''.join([bin(x)[2:].zfill(8) for x in bytes])
    # calculate the size of data to store, this will be the first 22 bits of
    # encoded data, allowing for a maximum of 4 GB to be hidden per file.
    payload_size = min((len(elements) * 70) - 22, len(bytes) * 8)
    bits = bin(payload_size)[2:].zfill(22) + bits
    # calculate capacity
    num_bits = payload_size + 22
    bit_index = 0
    for each in elements:
        # don't store more data than intended
        if bit_index >= num_bits:
            break
        bit_index = set_grass_bits(each, bits, bit_index)
    return None


def get_grass_bits(element):
    """
    Given a lxml.Element representing a PlantGrass or PlantTallGrass thing,
    extract the data encoded in it according to our unique method. Returns 70
    bits normally, 50 bits in the rare cases where the "age" property is
    missing.
    :param element: The PlantGrass/PlantTallGrass element with hidden data.
    :type element: lxml.Element
    :return: The raw bits that were hidden in the element.
    :rtype: str
    """
    bits = str()
    # the numerical digits after the name conceal the 18 bits of data in id
    # example: PlantGrass0256 = 256
    id = int(element[1].text[len(element[0].text):])
    bits += bin(id)[2:].zfill(18)
    # the health is an integer from 5 to 85, we use 6 bits of it.
    health = int(element[4].text) - 5
    bits += bin(health)[2:].zfill(6)
    # we're assuming that we have 8 decimal digits in the fractional part of
    # growth, giving us 26 bits
    growth = Decimal(element[5].text) * Decimal(100000000)
    bits += bin(int(growth))[2:].zfill(26)
    # in a few rare cases, the age attribute doesn't exist
    try:
        # if it does, it holds 20 bits of information
        age = int(element[6].text)
        bits += bin(age)[2:].zfill(20)
    except:
        pass
    return bits


def bytes_from_grasses(elements):
    """
    Decodes the data hidden in list of PlantGrass and PlantTallGrass elements.
    We assume that the first 22 bits of encoded data is the size of the payload
    (excluding itself) in bits. This thus covers a maximum capacity of 4
    gigabytes per cover file.
    :param elements: The elements concealing the data.
    :type elements: list
    :return: The bytes of encoded data, with zero-padding.
    :rtype: list
    """
    # find out how many bits are stored in the elements
    num_bits = int(get_grass_bits(elements[0])[:22], 2) + 22
    # don't return the bits encoding the size, just the raw payload
    bits = get_grass_bits(elements[0])[22:]
    # decode the bits from all remaining elements, if necessary
    index = 1
    while index < len(elements):
        # don't read more data than is encoded
        if len(bits) >= num_bits:
            break
        bits += get_grass_bits(elements[index])
        index += 1
    # zero pad so we can return bytes, not bits
    bits = bits[:num_bits-22]
    if len(bits) % 8 != 0:
        bits += '0' * int(math.ceil(len(bits) / 8.0) - len(bits))
    # convert bits to bytes
    index = 0
    bytes = list()
    while index < len(bits):
        bytes.append(int(bits[index:index+8],2))
        index += 8
    return bytes


def encode_in_grasses(cover_filename, payload_filename, result_filename):
    """
    Given a cover file and a payload to embed, encode the payload in
    result_filename as plant grasses.
    :param cover_filename: The filename of the save file to model our result after.
    :type cover_filename: str
    :param payload_filename: The filename of the file to conceal in the result.
    :type payload_filename: str
    :param result_filename: The filename to use for the resulting file.
    :type result_filename: str
    """
    # get our cover file, find the Plant things
    root = load_savefile(cover_filename)
    my_elements = find_grass_elements(root)

    # get the raw bytes of our payload
    payload = get_bytes_from_file(payload_filename)

    # encode the payload in the fields of the plant elements
    bytes_to_grasses(my_elements, payload)

    # write the resulting file to disk
    with open(result_filename, 'w') as f:
        f.write(etree.tostring(root, pretty_print=True))


def decode_from_grasses(encoded_filename, result_filename):
    """
    Opens a file with data concealed in the Plant things, extracts the
    data, and writes it to disk.
    :param encoded_filename: The filename concealing the data we want.
    :type encoded_filename: str
    :param result_filename: The filename to write the extracted data to.
    :type result_filename: str
    """
    root = load_savefile(encoded_filename)

    # extract the encoded data
    my_elements = find_grass_elements(root)
    bytes = bytes_from_grasses(my_elements)

    # write the results to disk
    with open(result_filename, 'wb') as f:
        f.write(''.join([chr(x) for x in bytes]))


def find_floating_point_elements(root):
    """
    Return a list of lxml elements that have floating-point values.
    :param root: The
    :return:
    """
    my_floats = list()
    for element in root.iter():
        if len(element) == 0 and element.text is not None and element.text.find('.') > 0:
            try:
                x = float(element.text)
                my_floats.append(element)
            except:
                continue
    return my_floats


def recursive_children(e):
    num_children = 0
    if hasattr(e, '_children'):
        for each in e._children:
            num_children += recursive_children(each) + 1
    return num_children


def bytes_to_whitespace(bytes):
    """
    Given a list of bytes, return a string of whitespace.
    :param bytes: The bytes to encode in whitespace.
    :type bytes: list
    :return: The whitespace string of spaces (zeroes) and tabs (ones).
    :rtype: str
    """
    whitespace = ''.join([bin(x)[2:].zfill(8) for x in bytes])
    whitespace = whitespace.replace('0', ' ').replace('1', '\t')
    return whitespace


def whitespace_to_bytes(whitespace):
    """
    Given a string of whitespace, return the encoded binary message.
    :param whitespace: A series of spaces and tabs, representing zeroes and ones.
    :type whitespace: str
    :return: The encoded bytes as a list of ints (bytes).
    :rtype: list
    """
    # convert spaces to 0 and tabs to 1
    message = whitespace.replace(' ', '0').replace('\t', '1')
    # add padding to the end, if necessary
    if len(message) % 8 != 0:
        message += '0' * (8 - (len(message) % 8))
    # convert to bytes
    my_bytes = list()
    index = 0
    while index  < len(message):
        # read one byte at a time
        my_bytes.append(int(message[index:index+8], 2))
        index += 8
    return my_bytes


def intersperse_whitespace(cover_list, whitespace):
    """
    Given a list of xml tags, intersperse whitespace before, between, and after tags.
    :param cover_list: The list of xml tags (strings).
    :type cover_list: list
    :param whitespace: The string of whitespace to mix in with the tags.
    :type whitespace: str
    :return: The string of encoded text
    :rtype: str
    """
    results = str()
    index = 0
    cover_list = etree.tostring(etree.fromstring(''.join(cover_list)), pretty_print=True).split('\n')
    minimum = min(len(cover_list), len(whitespace))
    while index < minimum:
        results += cover_list[index] + whitespace[index] + '\n\r'
        index += 1
    if len(cover_list) > len(whitespace):
        results += '\n\r'.join(cover_list[index:]) + '\n\r'
    else:
        results += whitespace[index:]
    return results


def extract_whitespace(encoded_text):
    """
    Given a string of xml, return the string of whitespace produced by removing all tags.
    :param encoded_text: The string of xml with encoded whitespace.
    :type encoded_text: str
    :return: The whitespace outside of and between tags.
    :rtype: str
    """
    whitespace = list()
    encoded_lines = encoded_text.split('\n\r')
    for each in encoded_lines[:-1]:
        # get the whitespace character at the end of each line, right before the newline
        if each[-1] in [' ', '\t']:
            whitespace.append(each[-1])
        else:
            # whitespace character is only missing if there's no more encoded data, so quit
            break
    else:
        try:
            # may or may not be more encoded data than lines, so look at unique characters in the last line
            characters = list(set([x for x in encoded_text[-1]]))
            # if there's more than two types of characters it can't be just spaces and tabs
            if len(characters) > 2:
                Exception('Not whitespace.')
            # make sure we're only dealing with spaces and tabs
            for each in characters:
                if each not in [' ', '\t']:
                    Exception('Not whitespace.')
            # add the sequence of whitespace to what we've already collected
            whitespace += [x for x in encoded_lines[-1]]
        except:
            pass
    return ''.join(whitespace)


def extract_tags(text):
    """
    Given a string of xml, return a list of tokens, with surrounding whitespace removed.
    :param text: The string of valid xml.
    :type text: str
    :return: The list of xml tokens.
    :rtype: list
    """
    # split the string wherever tags immediately follow each other to ensure we strings like
    # "<gameversion>0.18.1722 rev1198</gameversion>" are kept together
    tokens = text.split('><')
    tokens = ['<' + x + '>' for x in tokens]
    tokens[0] = tokens[0][1:]
    tokens[-1] = tokens[-1][:-1]
    return tokens


def get_bytes_from_file(filename):
    """
    Load the raw bytes of a file as a string of ints.
    :param filename: The filename to load from.
    :type filename: str
    :return: The list of bytes (ints).
    :rtype: list
    """
    payload = list()
    with open(filename, 'rb') as f:
        byte = f.read(1)
        while byte != '':
            payload.append(ord(byte))
            byte = f.read(1)
    return payload


def encode(cover_filename, payload_filename, result_filename):
    """
    Given a cover file and a payload to embed, encode the payload in
    result_filename as whitespace.
    :param cover_filename: The filename of the save file to model our result after.
    :type cover_filename: str
    :param payload_filename: The filename of the file to conceal in the result.
    :type payload_filename: str
    :param result_filename: The filename to use for the resulting file.
    :type result_filename: str
    """
    # get our cover file, remove whitespace from it
    with open(cover_filename, 'r') as f:
        tokens = extract_tags(f.read().replace('\n', '').replace('\r', '').replace('\t', ''))

    # get the raw bytes of our payload
    payload = get_bytes_from_file(payload_filename)

    # encode the payload as whitespace, then mix it in with the cover file
    whitespace = bytes_to_whitespace(payload)
    encoded_text = intersperse_whitespace(tokens, whitespace)

    # write the resulting file to disk
    with open(result_filename, 'w') as f:
        f.write(encoded_text)


def decode(encoded_filename, result_filename):
    """
    Opens a file with data concealed in whitespace, extracts the data, and
    writes it to disk.
    :param encoded_filename: The filename concealing the data we want.
    :type encoded_filename: str
    :param result_filename: The filename to write the extracted data to.
    :type result_filename: str
    """
    with open(encoded_filename, 'r') as f:
        # remove irrelevant whitespace
        whitespace = extract_whitespace(f.read())

    # extract the encoded data
    bytes = whitespace_to_bytes(whitespace)

    # write the results to disk
    with open(result_filename, 'wb') as f:
        f.write(''.join([chr(x) for x in bytes]))


def bytes_to_floats(floats, payload):
    """
    Given a list of lxml Elements holding floating point values, store the
    list of bytes as their decimal fractions. Additionally, use the first four
    bytes of the cover floats to indicate how many bytes are being stored.
    :param floats: The list of lxml Elements to modify.
    :type floats: list
    :param payload: The list of bytes to conceal.
    :type payload: list
    """
    # calculate the number of bytes to store
    num_bytes = len(payload)
    # only store as much data as we have room for
    if num_bytes + 4 > len(floats): # TODO - Implement more aggressive mode, two bytes in fraction and two bytes in whole number
        num_bytes = len(floats) - 4
    bytes = list()
    # the first four concealed bytes are the number of stored bytes (not counting these four)
    for i in range(4):
        bytes.append(float((num_bytes >> ((3 - i) * 8)) & 255) * 0.001)
    bytes += [float(x) * 0.001 for x in payload]
    # store the bytes as the decimal fractions of the first num_bytes floats
    for index in range(num_bytes + 4):
        floats[index].text = str(bytes[index] + math.floor(float(floats[index].text)))


def floats_to_bytes(floats, num_bytes=None):
    """
    Given a list of lxml Elements, extract the number of bytes stored, and
    then those bytes.
    :param floats: The list of lxml Elements with data concealed in their
    decimal fractions.
    :type floats: list
    :param num_bytes: Optional argument indicating the number of bytes to be
    retrieved.
    :type num_bytes: list
    :return: The list of bytes retrieved from the Elements.
    :rtype: list
    """
    bytes = list()
    if num_bytes is None:
        num_bytes = 0
        for index in range(4):
            bytes.append((int((Decimal(floats[index].text) - Decimal(math.floor(Decimal(floats[index].text)))) * 1000)))
        for i in range(4):
            num_bytes += bytes[i] * (2 ** (8 * (3 - i)))
    for index in range(4, num_bytes+4):
        bytes.append((int((Decimal(floats[index].text) - Decimal(math.floor(Decimal(floats[index].text)))) * 1000)))
    return bytes


def encode_in_floating_point(cover_filename, payload_filename, result_filename):
    """
        Given a cover file and a payload to embed, encode the payload in
        result_filename as whitespace.
        :param cover_filename: The filename of the save file to model our result after.
        :type cover_filename: str
        :param payload_filename: The filename of the file to conceal in the result.
        :type payload_filename: str
        :param result_filename: The filename to use for the resulting file.
        :type result_filename: str
    """
    # get our cover file, remove whitespace from it
    root = load_savefile(cover_filename)
    my_floats = find_floating_point_elements(root)

    # get the raw bytes of our payload
    payload = get_bytes_from_file(payload_filename)

    # encode the payload as floating-point numbers
    bytes_to_floats(my_floats, payload)

    # write the resulting file to disk
    with open(result_filename, 'w') as f:
        f.write(etree.tostring(root, pretty_print=True))


def decode_from_floating_point(encoded_filename, result_filename):
    """
    Opens a file with data concealed in the decimal fractions, extracts the
    data, and writes it to disk.
    :param encoded_filename: The filename concealing the data we want.
    :type encoded_filename: str
    :param result_filename: The filename to write the extracted data to.
    :type result_filename: str
    """
    root = load_savefile(encoded_filename)

    # extract the encoded data
    my_floats = find_floating_point_elements(root)
    bytes = floats_to_bytes(my_floats)[4:]

    # write the results to disk
    with open(result_filename, 'wb') as f:
        f.write(''.join([chr(x) for x in bytes]))


def main():
    encode('Nova.rws', 'target.gif', 'Subtle.rws')
    decode('Subtle.rws', 'decoded_gif.gif')

    # encode_in_floating_point('Nova.rws', 'Nova.txt', 'Subtle.rws')
    # decode_from_floating_point('Subtle.rws', 'decoded_gif.gif')

    # encode_in_grasses('Nova.rws', 'Nova.txt', 'Subtle.rws')
    # decode_from_grasses('Subtle.rws', 'decoded_gif.gif')

    pass


if __name__ == '__main__':
    example = 'Examples:\n\r'
    example += '$ python rimworld_stego.py -e -i data_to_conceal.txt -s savefile.rws\n\r'
    example += '$ python rimworld_stego.py -i data_to_conceal.txt -s savefile.rws -o modified_savefile.rws\n\r'
    example += '$ python rimworld_stego.py -d -s savefile.rws -o decoded_data.txt\n\r'
    parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description='RimWorldStego - Conceal data in RimWorld save files', epilog=example)

    subgroup = parser.add_argument_group('Main arguments')
    mex_group = subgroup.add_mutually_exclusive_group(required=True)
    mex_group.add_argument('-d', metavar='DECODE', help='Decode the data stored in the savefile.')
    mex_group.add_argument('-e', metavar='ENCODE', help='Encode data into the savefile.')
    subgroup.add_argument('-i', metavar='INFILE', dest='infile', help='Specify the file to be hidden in a savefile.')
    subgroup.add_argument('-s', metavar='SAVEFILE', dest='savefile', help='The savefile to extract the data from or encode into.', required=True)
    subgroup.add_argument('-o', metavar='OUTFILE', dest='outfile', help='Specify the filename for the encoded savefile, if different from the original.')

    subgroup2 = parser.add_argument_group('Encoding schemes')
    mex_group2 = subgroup2.add_mutually_exclusive_group(required=True)
    # ????
    # mex_group2.add_argument(help='Edit timestamps')  # ????
    # ????
    mex_group2.add_argument('-gm', metavar='GENERATE_MAP', help='Generate map elements')
    mex_group2.add_argument('-mm', metavar='MODIFY_MAP', help='Modify map elements')
    mex_group2.add_argument('-gl', metavar='GENERATE_LOG', help='Generate play log events')
    mex_group2.add_argument('-ml', metavar='MODIFY_LOG', help='Modify play log events')

    # main()
    if len(sys.argv) is 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()



