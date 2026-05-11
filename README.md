# LLM Garous

<img src="https://upload.wikimedia.org/wikipedia/fr/thumb/2/2c/Loups-garous_de_Thiercelieux.png/500px-Loups-garous_de_Thiercelieux.png" width="200"/>

Codebase for our project at [ISC](https://isc.hevs.ch/) to play a game of "Loups-Garous" with LLMs.

## How to clone

```bash
git clone https://github.com/renaud/werewolves.git werewolves
cd werewolves
```

Then create an empty private repository on GitHub called `werewolves` and push your clone to it:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/werewolves.git
git push -u origin main
```


## Instructions

[projet_loups_garous.pdf](projet_loups_garous.pdf)


## How to run

Install dependencies:
```bash
pip install -r requirements.txt
```

Implement your `WerewolfPlayer` in `werewolf.py`

Start the players with:
```bash
python3 local_players.py
```

If you have configured remote players in `players_config.yaml`, wake them up first by running:  
```bash
python3 ping.py
```


Start the game leader with:
```bash
python3 game_leader.py
```


## How to publish your player as a web service using Render

Render.com is a platform that allows you to deploy your web service for free.

### Login

https://dashboard.render.com/login, sign with github
verify email, skip survey

### Create a new web service

- click on [Web service](https://dashboard.render.com/web/new?onboarding=active)
- select your repository: `werewolves`
- keep default settings, except for 
    - "Start Command", replace with: `gunicorn --workers 1 --threads 4 --timeout 120 app:app`
    - "Instance Type", select "Free"
- click "Deploy Web Service", then wait 
- at some point, a message box will appear with a URL to your web service
- share the URL with the game leader (so other teams can add it to their `players_config.yaml` and play against your player)
