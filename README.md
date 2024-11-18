## Automatic attendance

### Setup

> Note! This will require buying/using openai credits for image detection

1. Install uv (better pip- https://github.com/astral-sh/uv)
   `curl -LsSf https://astral.sh/uv/install.sh | sh`

2. `uv venv`

3. `source .venv/bin/activate`

4. `uv pip install -r requirements.txt`

5. Creating environment variables/openai setup

- `cp env.example .env`
- Go to https://platform.openai.com/settings/organization/general and get your Organization ID
- save it to `ORG=<...>` in your .env
- Go to https://platform.openai.com/settings/organization/projects to create an openai project
- Create a project img here
- Add the project id to
  PROJECT=<project-id>
  in your .env
- go to api keys img here
- create an api key with the project you just created
- add the api key to .env
  `API_KEY=...`

6. Take a clear image of the names on the recitation assignment "name" section

7. Add all images to the /images directory

8. Add all your grade blanks to /sheets as .csv files

9. `python3 automate.py`

10. csv outputs will be in `output_sheets`

You can view attendance_processing.log for anything
that went wrong.

The script will output to stdout if the users name could not be matched.
If that's the case you should manually review the image
