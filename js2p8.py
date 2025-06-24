import re
import json
import sys


HEADER = """pico-8 cartridge // http://www.pico-8.com
version 0
__lua__
"""

class BitReader:
    def __init__(self, data):
        self.data = data
        self.byte_index = 0
        self.bit_index = 0  # 0 = LSB, 7 = MSB
    
    def read_bit(self):
        if self.byte_index >= len(self.data):
            raise ValueError("Input data exhausted")
        
        byte = self.data[self.byte_index]
        bit = (byte >> self.bit_index) & 1
        self.bit_index += 1
        
        if self.bit_index == 8:
            self.bit_index = 0
            self.byte_index += 1
            
        return bit
    
    def read_bits(self, n):
        value = 0
        for i in range(n):
            bit = self.read_bit()
            value |= (bit << i)  # LSB-first
        return value

def decompress(compressed_data, decompressed_len):
    mtf = list(range(256))  # Initialize MTF: [0, 1, 2, ..., 255]
    output = []
    reader = BitReader(compressed_data)
    
    while len(output) < decompressed_len:
        header_bit = reader.read_bit()
        
        if header_bit == 1:  # Case: byte from MTF
            # Read unary
            unary = 0
            while reader.read_bit() == 1:
                unary += 1
            
            # Calculate index
            unary_mask = (1 << unary) - 1
            num_bits = 4 + unary
            bits_val = reader.read_bits(num_bits)
            index = bits_val + (unary_mask << 4)
            
            # Get byte and update MTF
            byte_val = mtf[index]
            del mtf[index]
            mtf.insert(0, byte_val)
            output.append(byte_val)
            
        else:  # Case: LZ77 sequence
            # Read offset size
            if reader.read_bit() == 1:
                if reader.read_bit() == 1:
                    offset_bits = 5
                else:
                    offset_bits = 10
            else:
                offset_bits = 15
            
            # Read offset
            offset = reader.read_bits(offset_bits) + 1
            
            # Special case: uncompressed block
            if offset_bits == 10 and offset == 1:
                while True:
                    byte_val = reader.read_bits(8)
                    if byte_val == 0:  # End of block
                        break
                    output.append(byte_val)
                    if len(output) >= decompressed_len:
                        break
            else:
                # Read length
                length = 3
                while True:
                    part = reader.read_bits(3)
                    length += part
                    if part != 7:
                        break
                
                # Copy sequence from output
                start = len(output) - offset
                if start < 0:
                    raise ValueError(f"Invalid offset: {offset} (output len={len(output)})")
                
                for i in range(length):
                    if len(output) >= decompressed_len:
                        break
                    output.append(output[start + i % offset])
    
    return bytes(output)

def format_gfx(gfx_bytes):
    gfx_lines = []
    for y in range(128):  # 128 rows
        row = []
        for x in range(64):  # 64 bytes * 2 pixels = 128 pixels
            byte = gfx_bytes[y * 64 + x]
            lo = byte & 0x0F
            hi = (byte >> 4) & 0x0F
            row.append(f"{lo:x}{hi:x}")
        gfx_lines.append(''.join(row))
    return '\n'.join(gfx_lines)

def format_map(map_bytes):
    map_lines = []
    for i in range(0, len(map_bytes), 128):  # 128 tiles por fila
        row_bytes = map_bytes[i:i+128]
        map_lines.append(''.join(f"{b:02x}" for b in row_bytes))
    return '\n'.join(map_lines)

def format_sfx(sfx_bytes):
    lines = []
    for i in range(64):  # 64 sfx entries
        offset = i * 68
        entry = sfx_bytes[offset:offset + 68]
        notes = entry[:64]
        editor_mode = entry[64]
        note_duration = entry[65]
        loop_start = entry[66]
        loop_end = entry[67]

        # Convert header
        line = f"{editor_mode:02x}{note_duration:02x}{loop_start:02x}{loop_end:02x}"

        # Convert notes (32 notes = 64 bytes, 5 nibbles per note = 160 nibbles = 40 bytes = 80 hex chars)
        for j in range(0, 64, 2):
            lsb = notes[j]
            msb = notes[j + 1]
            pitch = lsb & 0x3F
            waveform = ((msb & 0x80) >> 4) | ((msb & 0x01) << 2) | ((lsb & 0xC0) >> 6)
            volume = (msb >> 1) & 0x07
            effect = (msb >> 4) & 0x07
            line += f"{pitch:02x}{waveform:x}{volume:x}{effect:x}"

        lines.append(line)
    return '\n'.join(lines)

def format_gff(gff_bytes):
    """Formatea 256 bytes de datos gff en 2 líneas hexadecimales (128 bytes por línea)."""
    lines = []
    for i in range(0, 256, 128):  # Procesar en chunks de 128 bytes
        chunk = gff_bytes[i:i+128]
        hex_line = ''.join(f"{b:02x}" for b in chunk)
        lines.append(hex_line)
    return '\n'.join(lines)

def main():
    if len(sys.argv) < 2:
        print("Usage: python js2p8.py <game.js>")
        sys.exit(1)
    
    filename = sys.argv[1]
    
    # 1. Read the file
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()

    pattern_name = r"var\s+_cartname\s*=\s*\[\s*`([^`]*)`\s*\];"
    pattern_data = r"var\s+_cartdat\s*=\s*(\[[\s\S]*?\]);"

    match = re.search(pattern_name, content)

    cart_name = "game.p8"
    if match:
        cart_name = match.group(1)

    match = re.search(pattern_data, content)

    if match:
        array_str = match.group(1)

        try:
            cartdat_list = json.loads(array_str)


            cartdat_bytes = bytes(cartdat_list)

            gfx_data   = cartdat_bytes[0x0000:0x2000]
            map_lower  = cartdat_bytes[0x1000:0x2000]
            map_upper  = cartdat_bytes[0x2000:0x3000]
            map_data   = map_upper + map_lower
            gff_data   = cartdat_bytes[0x3000:0x3100]
            sfx_data   = cartdat_bytes[0x3200:0x4300]

            signature = cartdat_bytes[0x4300:0x4304]
            decompressed_len = int.from_bytes(cartdat_bytes[0x4304:0x4306], byteorder='big')
            compressed_len_plus_8 = int.from_bytes(cartdat_bytes[0x4306:0x4308], byteorder='big')
            compressed_data = cartdat_bytes[0x4308:0x4308 + (compressed_len_plus_8 - 8)]

            decompressed_data = decompress(compressed_data, decompressed_len)

            with open(cart_name, 'w', encoding='utf-8') as f:
                f.write(HEADER)
                f.write(decompressed_data.decode('utf-8', errors='backslashreplace').replace(r'\x94', '⬆️').replace(r'\x83', '⬇️').replace(r'\x8b', '⬅️').replace(r'\x91', '➡️').replace(r'\x8e', '🅾️').replace(r'\x97', '❎'))


                f.write("\n__gfx__\n")
                f.write(format_gfx(gfx_data))

                f.write("\n__map__\n")
                f.write(format_map(map_data))

                f.write("\n__gff__\n")  # Nueva sección
                f.write(format_gff(gff_data))

                f.write("\n__sfx__\n")
                f.write(format_sfx(sfx_data))


            print("Signature:", signature)
            print("Decompressed size:", decompressed_len)
            print("Compressed size (+8):", compressed_len_plus_8)
            print("Compressed bytes:", compressed_data[:8], "...")
            print(f"Saved in {cart_name}")
        except json.JSONDecodeError:
            print("Error decoding JSON.")
    else:
        print("Variable _cartdat not found.")

if __name__ == "__main__":
    main()

