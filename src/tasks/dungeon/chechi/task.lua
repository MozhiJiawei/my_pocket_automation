local claimed_card = require('tasks.dungeon.chechi.assets.claimed_card')
claimed_card.variants = {require('tasks.dungeon.chechi.assets.claimed_card_current')}

return {
    id = 'chechi', -- Current in-game title is 车迟斗法.
    list_name = require('tasks.dungeon.chechi.assets.list_name'),
    card = require('tasks.dungeon.chechi.assets.card'),
    claimed_card = claimed_card,
    ended_after_claim = true,
    title = require('tasks.dungeon.chechi.assets.title'),
    completed = require('tasks.dungeon.chechi.assets.completed'),
    final_done = require('tasks.dungeon.chechi.assets.final_done'),
}
