import os
from io import BufferedReader, BytesIO, SEEK_SET
from argparse import ArgumentParser, Namespace
from typing import Tuple
from time import perf_counter
from dataclasses import dataclass
import json
from googletrans import LANGUAGES, Translator
from googletrans.models import Translated
import progressbar as bar

LANG_CODES: list[str] = [key for key in LANGUAGES.keys()]

DEFAULT_FIRST_THAILAND_BYTE = 92508
'''Decimal byte position in translation file'''

DEFAULT_LAST_THAILAND_BYTE = 13807635
'''Decimal byte position in translation file'''

DEFAULT_TRANSLATION_BATCH_SIZE = 5

class SpecialExpressions:
	@staticmethod
	def has_special_char(value: str, chars: list[str] = ['[', '{', '<']) -> bool:
		'''Checks if str contains one of special characters'''
		for c in chars:
			if c in value:
				return True
			
		return False
	
	@staticmethod
	def split_str(value: str, 
				  expressions_delimiters: list[Tuple[str, str]] = 
				  	[('[', ']'), ('{', '}'), ('<', '>')]
				  ) -> list[str]:
		if not SpecialExpressions.has_special_char(value):
			return [value]
		
		result: list[str] = []

		while True:
			if not SpecialExpressions.has_special_char(value):
				return result + [value]

			open_delimiter_positions: dict[int, Tuple[str, str]] = {}
			for pair in expressions_delimiters:
				if pair[0] in value:
					open_delimiter_positions[value.find(pair[0])] = pair

			open_position: int = len(value)
			for position in open_delimiter_positions:
				open_position = min(open_position, position)

			delimiters = open_delimiter_positions[open_position]
			if open_position > 0:
				result.append(value[0:open_position])

			close_position: int = value.find(delimiters[1])
			# added trailing spaces because Google Translate removes them at translation
			result.append(f'{value[open_position:close_position + 1]}')

			value = value[close_position + 1:]

class Args(Namespace):
	'''Parses and holds command line arguments'''
	input_file: str
	output_file: str
	source_lang_code: str
	target_lang_code: str
	output_file_type: str
	first_byte: int
	last_byte: int
	replace_file: str
	replace_file_type: str
	replace_first_byte: int
	replace_last_byte: int
	batch_size: int
	
	@staticmethod
	def parse() -> 'Args':
		argparser = ArgumentParser(prog='sandrock-translator', epilog=f'Possible language codes: {" ".join(LANG_CODES)}')
		argparser.add_argument('input_file', type=str, help='Path to original translation file')
		argparser.add_argument('output_file', type=str, help='Path to target translation file')
		argparser.add_argument('-s', '--source_lang_code', type=str, default='auto', choices=['auto', *LANG_CODES], help='Force translation source language code. auto will detect language. default: auto')
		argparser.add_argument('-t', '--target_lang_code', type=str, default='', choices=LANG_CODES, help='Target language code. If not specified translation step will be skipped.')
		argparser.add_argument('-o', '--output_file_type', type=str, default='binary', choices=['binary', 'json'], help='default: binary')
	
		group_positions = argparser.add_argument_group('Byte positions')
		group_positions.add_argument('-f', '--first_byte', type=int, default=DEFAULT_FIRST_THAILAND_BYTE, help=f'Translation sector first byte position in decimal number. Program will start translating from this position. default: {DEFAULT_FIRST_THAILAND_BYTE}')
		group_positions.add_argument('-l', '--last_byte', type=int, default=DEFAULT_LAST_THAILAND_BYTE, help=f'Translation sector last byte position in decimal number. Program will end translation at this position. default: {DEFAULT_LAST_THAILAND_BYTE}')
		
		group_splicing = argparser.add_argument_group('Replacing', description='Use another translation file as text source instead of input_file. Remember to set replace byte positions when replacement file type is set to binary')
		group_splicing.add_argument('-r', '--replace_file', type=str, default='', help='Source file of replacement translation strings. Must be used with both --replace_first_byte and --replace_last_byte when replacement file type is set to binary')
		group_splicing.add_argument('-R', '--replace_file_type', type=str, default='json', choices=['binary', 'json'], help='Replace file type. default: json')
		group_splicing.add_argument('--replace_first_byte', type=int, default=-1, help='Replace Translation sector first byte position in decimal number. Must be used with both --replace_file and --replace_last_byte when --replace_file_type is set to binary')
		group_splicing.add_argument('--replace_last_byte', type=int, default=-1, help='Replace Translation sector last byte position in decimal number. Must be used with both --replace_file and --replace_first_byte when --replace_file_type is set to binary')
		
		group_utils = argparser.add_argument_group('Utils')
		group_utils.add_argument('-b', '--batch_size', type=int, default=DEFAULT_TRANSLATION_BATCH_SIZE, help=f'Number of strings per translation request. default: {DEFAULT_TRANSLATION_BATCH_SIZE}')

		parsed = argparser.parse_args(namespace=Args())

		if not os.path.exists(parsed.input_file):
			print('Input file does not exist!')
			argparser.print_usage()
			exit()

		replace_count = 0
		if parsed.replace_file != '':
			replace_count += 1
		if parsed.replace_first_byte > -1:
			replace_count += 1
		if parsed.replace_last_byte > -1:
			replace_count += 1

		if replace_count > 0 and replace_count < 3 and parsed.replace_file_type == 'binary':
			print('Replace arguments must be set together!')
			argparser.print_usage()
			exit()

		return parsed

class ProgressTracker:
	def __init__(self, total: int):
		self._total = total or 1
		self._last_timestamp: float = perf_counter()
		self._last_current = 0
		self._progress_bar = bar.ProgressBar(maxval=total, widgets=[
			'Progress: ',
			bar.Percentage(), ' ',
			bar.Bar('*', left='[', right=']'), ' | ',
			bar.Counter(),
			f'/{total} Units', ' | ',
			bar.Timer(), ' | ',
			bar.ETA(), ' | ',
			'Speed: --.- Units/s'
		])
		self._progress_bar.start()

	def next(self, current: int):
		timestamp: float = perf_counter()
		try:
			speed: float = (current - self._last_current) / (timestamp - self._last_timestamp)
		except ZeroDivisionError:
			speed = 0
		
		self._progress_bar.widgets[-1] = f'Speed: {speed:.1f} Units/s' # type: ignore
		self._progress_bar.update(current) # type: ignore
		
		self._last_timestamp = timestamp
		self._last_current = current

	def finish(self):
		self._progress_bar.finish()

@dataclass
class TranslationResult:
	units: list['TranslationUnit']
	omitted: int

ByteSize = int

@dataclass
class TranslationUnit:
	id: int
	size: ByteSize
	text: str

	def replace(self, replacer: 'TranslationUnit') -> bool:
		'''Replace original translation text with replacer translation text'''
		replacer_text_bytes: bytes = replacer.text.encode()
		if (SpecialExpressions.has_special_char(self.text) \
		    or SpecialExpressions.has_special_char(replacer.text))\
		    and len(replacer_text_bytes) > self.max_size:
			
			return False

		self.text = (replacer_text_bytes[:self.max_size]).decode(errors='ignore')
		return True

	def to_dict(self) -> dict: # type: ignore
		return {'id': self.id, 'size': self.max_size, 'text': self.text} # type: ignore

	@property
	def bytes(self) -> bytes:
		return bytes().join(
			[
				self.id.to_bytes(4, byteorder='little'),
				self.max_size.to_bytes(4, byteorder='little'),
				self.text.encode()[:self.max_size],
				b'\x00' * (self.max_size - len(self.text.encode()))
			]
		)

	@property
	def max_size(self) -> ByteSize:
		if self.size % 4 == 0:
			return self.size

		return self.size + (4 - self.size % 4)

	@staticmethod
	def from_dict(value: dict) -> 'TranslationUnit': # type: ignore
		id: int = value['id'] # type: ignore
		size: ByteSize = value['size'] # type: ignore
		text: str = value['text'] # type: ignore
		return TranslationUnit(id, size, text) # type: ignore

	@staticmethod
	def from_dict_list(value: list[dict]) -> list['TranslationUnit']: # type: ignore
		result: list[TranslationUnit] = []
		for d in value: # type: ignore
			result.append(TranslationUnit.from_dict(d)) # type: ignore

		return result

	@staticmethod
	def translate(original_units: list['TranslationUnit'], 
						original_language: str, 
						target_language: str) -> TranslationResult:
		'''Returns tuple of translated units and omitted strings'''
		def into_translation_payload(strings_parted: list[list[str]]) -> list[str]:
			def contains_at_least_alnum(string: str, occurrences: int) -> bool:
				counter = 0
				for c in string:
					if c.isalnum():
						counter += 1
					
					if counter == occurrences:
						return True
				return False
			
			payload: list[str] = []
			for unit_strings in strings_parted:
				for string in unit_strings:
					if SpecialExpressions.has_special_char(string):
						continue

					# Google Translate doesn't like translating single special
					# characters, whitespace and empty strings
					if not contains_at_least_alnum(string, 2):
						continue

					if string.isspace():
						continue

					payload.append(string)

			return payload
		
		translator = Translator()
		original_strings: list[str] = [unit.text for unit in original_units]
		strings_parted: list[list[str]] = \
			[SpecialExpressions.split_str(string) for string in original_strings]
		translation_payload: list[str] = into_translation_payload(strings_parted)

		translated: list[Translated] = \
			translator.translate(translation_payload, # type: ignore
								 src=original_language, 
								 dest=target_language) 

		for i in range(len(strings_parted)):
			for j in range(len(strings_parted[i])):
				for t in translated:
					if strings_parted[i][j] == t.origin:
						strings_parted[i][j] = t.text
		
		translated_strings: list[str] = \
			[' '.join(unit_strings) for unit_strings in strings_parted]
		
		result: list[TranslationUnit] = []
		omitted_strings = 0
		for i in range(len(original_units)):
			candidate: str = translated_strings[i]
			max_length: int = original_units[i].max_size

			if len(candidate.encode()) > max_length \
				   and SpecialExpressions.has_special_char(candidate):
				
				result.append(original_units[i])
				omitted_strings += 1
			else:
				result.append(TranslationUnit(original_units[i].id, 
								  			  max_length, 
											  text=candidate[:max_length]))

		return TranslationResult(result, omitted_strings)

	@staticmethod
	def translate_by_batch(original_units: list['TranslationUnit'], 
			   	  batch_size: int, 
				  origin_lang_code: str, 
				  target_lang_code: str) -> 'TranslationResult':
		translated_units: list[TranslationUnit] = []
		progress_tracker = ProgressTracker(len(original_units))
		omitted_strings = 0
		for i in range(0, len(original_units), batch_size):
			progress_tracker.next(i)
			next_batch = original_units[i:i + batch_size]
			try:
				translated_batch = \
					TranslationUnit.translate(next_batch,
													origin_lang_code,
													target_lang_code)
				translated_units += translated_batch.units
				omitted_strings += translated_batch.omitted
					
			except Exception as e:
				progress_tracker.finish()
				print(f'Occurred at batch: {next_batch}')
				raise e
		progress_tracker.finish()
		return TranslationResult(translated_units, omitted_strings)

	@staticmethod
	def replace_translations(original_units: list['TranslationUnit'], replace_units: list['TranslationUnit']) -> None:
		'''Replace original translation texts with replacer translation texts'''
		try:
			replace_map: dict[int, 'TranslationUnit'] = {}
			for s in replace_units:
				replace_map[s.id] = s

			replaced_counter = 0
			for o in original_units:
				if o.id in replace_map:
					if o.replace(replace_map[o.id]):
						replaced_counter += 1
				else:
					raise KeyError()
			print(f'Replaced {replaced_counter}/{len(replace_units)} units...')
		except KeyError:
			print('replace positions mismatch: Selected replace localization sector does not contain original localization unit ID!')
			exit(1)

	@staticmethod
	def replace_json_translations(original_units: list['TranslationUnit'], replace_file_path: str) -> None:
		with open(replace_file_path, 'r') as replace_file:
			try:
				units: list[TranslationUnit] = TranslationUnit.from_dict_list(json.load(replace_file)) # type: ignore
			except KeyError:
				print('Invalid source json file format!')
				exit(1)


class BinaryLocalizationParser:
	@staticmethod
	def parse(bytes_stream: BytesIO) -> 'TranslationUnit':
		id_bytes = bytes_stream.read(4)
		if len(id_bytes) < 4:
			raise EOFError()
		
		id = int.from_bytes(id_bytes, byteorder='little')
		original_length = int.from_bytes(bytes_stream.read(4), byteorder='little')
		text = bytes_stream.read(original_length).decode()

		parsed = TranslationUnit(id, original_length, text)

		if original_length < parsed.max_size:
			bytes_stream.seek((4 - original_length % 4), 1)

		return parsed
	
	@staticmethod
	def parse_batch(bytes_stream: BytesIO) -> list['TranslationUnit']:
		units: list[TranslationUnit] = []
		while True:
			try:
				units.append(BinaryLocalizationParser.parse(bytes_stream))
			except EOFError:
				break

		return units

	@staticmethod
	def parse_sector(file: BufferedReader, start: int, stop: int) -> list['TranslationUnit']:
		file.seek(start, SEEK_SET)
		original_bytes = file.read(stop - start + 1)
		return BinaryLocalizationParser.parse_batch(BytesIO(original_bytes))

def cli():
	try:
		args = Args.parse()
	
		# Parsing units
		print('Parsing original translations...')
		with open(args.input_file, 'rb') as replace_file:
			units: list[TranslationUnit] = \
						BinaryLocalizationParser.parse_sector(replace_file, 
															args.first_byte, 
															args.last_byte)
			
		# Splicing
		if args.replace_file != '':
			print('Parsing splicing translations...')
			replace_units: list[TranslationUnit] = []
			match args.replace_file_type:
				case 'binary':
					with open(args.replace_file, 'rb') as replace_file:
						replace_units = \
							BinaryLocalizationParser.parse_sector(replace_file, 
																args.replace_first_byte, 
																args.replace_last_byte)
						
				
				case 'json':
					with open(args.replace_file, 'r') as replace_file:
						try:
							replace_units = TranslationUnit.from_dict_list(json.load(replace_file)) # type: ignore
						except KeyError:
							print('Invalid source json file format!')
							exit(1)
				case _:
					pass

			print('Splicing translations...')
			TranslationUnit.replace_translations(units, replace_units)
			

		# Translating
		if args.target_lang_code != '' and args.target_lang_code != args.source_lang_code:
			print(f'Translating {len(units)} units...')
			translation_result = TranslationUnit.translate_by_batch(units, 
																	args.batch_size, 
																	args.source_lang_code, 
																	args.target_lang_code)
			print(f'Omitted {translation_result.omitted} too long translations with special expressions...')
			print(f'Overwriting {len(translation_result.units)} translated units...')
			units = translation_result.units

		# Writing units
		match args.output_file_type:
			case 'binary':
				with open(args.input_file, 'rb') as input, open(args.output_file, 'wb') as output:
					print('Copying original translation...')
					output.seek(0, SEEK_SET)
					output.write(input.read())
					translated_bytes = bytes().join(map(lambda x: x.bytes, units))
					output.seek(args.first_byte, SEEK_SET)
					output.write(translated_bytes)

			case 'json':
				with open(args.output_file, 'w') as output:
					print('Externalizing to json...')
					json.dump([u.to_dict() for u in units], output, indent=4, ensure_ascii=False) # type: ignore
			
			case _:
				pass

		print('Done')
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
	cli()