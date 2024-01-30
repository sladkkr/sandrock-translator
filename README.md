# My Time At Sandrock translation tool
## Description
sandrock-translator is a tool for translating localization files of My Time At Sandrock using popular translation API Google Translate. It handles two output formats for intermediate and final usage: JSON and Binary. JSON translation file can be used to manually fix context errors. JSON translation file as well as binary file can be used to replace text in original binary file, this technic is beneficial because some languages has longer words or contains multi-byte characters than original translation resulting in not fitting end results. This tool can't change original size of text string in bytes so those kind of workarounds were implemented.
## Installation
Tool is published to PYPI, use for example PIP
```sh
pip install --user sandrock-translator
```
## Example usage
Externalize translation strings from original binary file into editable JSON.
```sh
sandrock-translator -o json ./english ./english.json
```

Translate to Japanese and externalize translation strings into editable JSON.
```sh
sandrock-translator -o json -t jp ./thailand ./japanese.json
```

Use "thailand" translation file as origin and replace with our "japanese.json" strings into usable translation file.
```sh
sandrock-translator -r ./japanese.json ./thailand ./japanese
```

Translate Thai file into japanese language in one step.
```sh
sandrock-translator -t jp ./thailand ./japanese
```
## Development
This project uses Poetry for Python project management. [Poetry Project Site](https://python-poetry.org/)

## Why Thai?
### In short
You will fit longer words with non-latin characters.
### Reason
I recommend "thailand" translation file as translation source for it's longest allowed string sizes in bytes. My Time At Sandrock uses UTF-8 encoded strings in translations and Thai has longest words with biggest width of Unicode encoding in bytes per character across available options.