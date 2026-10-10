"""Real HA 2026.2 script/automation runtime, with only the physical actuator mocked.

Run separately on Python 3.14 with homeassistant==2026.2.0 and pytest-asyncio.
"""
import asyncio
from pathlib import Path

import pytest

pytest.importorskip('homeassistant')
pytest_asyncio = pytest.importorskip('pytest_asyncio')
import yaml
from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries
from homeassistant.const import EVENT_HOMEASSISTANT_START
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

CONTROLLER = 'automation.open_rec_reconcile_water_heater_boost'


async def settle(hass):
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()


async def permit(hass):
    await hass.services.async_call('timer', 'start', {'entity_id': 'timer.open_rec_bridge_lease'}, blocking=True)
    await hass.services.async_call('input_boolean', 'turn_on',
                                   {'entity_id': 'input_boolean.open_rec_surplus_window'}, blocking=True)
    await settle(hass)


async def revoke(hass):
    await hass.services.async_call('input_boolean', 'turn_off',
                                   {'entity_id': 'input_boolean.open_rec_surplus_window'}, blocking=True)
    await settle(hass)


@pytest_asyncio.fixture
async def heater(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await async_load_base_functionality(hass)
    package = yaml.safe_load((Path(__file__).parents[2] / 'examples/homeassistant/open_rec.yaml').read_text())
    # Shorten only the OFF confirmation timeout; production logic is unchanged.
    package['automation'][0]['actions'][0]['choose'][0]['sequence'][1]['timeout'] = {'milliseconds': 50}
    actuator = {'fail_off': False, 'pause_on': None, 'on_entered': asyncio.Event(), 'calls': []}

    async def turn_on(call):
        actuator['on_entered'].set()
        if actuator['pause_on'] is not None:
            await actuator['pause_on'].wait()
        actuator['calls'].append('on')
        hass.states.async_set('switch.water_heater', 'on')

    async def turn_off(call):
        actuator['calls'].append('off')
        if actuator['fail_off']:
            raise HomeAssistantError('actuator unavailable')
        hass.states.async_set('switch.water_heater', 'off')

    hass.services.async_register('switch', 'turn_on', turn_on)
    hass.services.async_register('switch', 'turn_off', turn_off)
    for domain in ('input_boolean', 'input_number', 'timer', 'automation'):
        assert await async_setup_component(hass, domain, package)
    await hass.async_start()
    hass.states.async_set('switch.water_heater', 'off')
    hass.states.async_set('sensor.water_heater_temperature', '40')
    await settle(hass)
    try:
        yield hass, actuator
    finally:
        if actuator['pause_on'] is not None:
            actuator['pause_on'].set()
        await hass.async_stop()


@pytest.mark.asyncio
async def test_window_start_and_stop(heater):
    hass, _ = heater
    await permit(hass)
    assert hass.states.get('switch.water_heater').state == 'on'
    await revoke(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    assert hass.states.get('input_boolean.open_rec_heater_boost').state == 'off'


@pytest.mark.asyncio
async def test_failed_off_retains_ownership_then_retries(heater):
    hass, actuator = heater
    await permit(hass)
    actuator['fail_off'] = True
    await revoke(hass)
    assert hass.states.get('input_boolean.open_rec_heater_boost').state == 'on'
    actuator['fail_off'] = False
    await hass.services.async_call('automation', 'trigger', {'entity_id': CONTROLLER}, blocking=True)
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    assert hass.states.get('input_boolean.open_rec_heater_boost').state == 'off'


@pytest.mark.asyncio
async def test_lease_expiry_stops_stale_on_permission(heater):
    hass, _ = heater
    await permit(hass)
    await hass.services.async_call('timer', 'start',
                                   {'entity_id': 'timer.open_rec_bridge_lease', 'duration': 1}, blocking=True)
    await asyncio.sleep(1.2)
    await settle(hass)
    assert hass.states.get('input_boolean.open_rec_surplus_window').state == 'on'
    assert hass.states.get('timer.open_rec_bridge_lease').state == 'idle'
    assert hass.states.get('switch.water_heater').state == 'off'


@pytest.mark.asyncio
async def test_revocation_during_inflight_on_ends_off(heater):
    hass, actuator = heater
    actuator['pause_on'] = asyncio.Event()
    await hass.services.async_call('timer', 'start', {'entity_id': 'timer.open_rec_bridge_lease'}, blocking=True)
    await hass.services.async_call('input_boolean', 'turn_on',
                                   {'entity_id': 'input_boolean.open_rec_surplus_window'}, blocking=True)
    await asyncio.wait_for(actuator['on_entered'].wait(), timeout=2)
    await hass.services.async_call('input_boolean', 'turn_off',
                                   {'entity_id': 'input_boolean.open_rec_surplus_window'}, blocking=True)
    actuator['pause_on'].set()
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    assert hass.states.get('input_boolean.open_rec_heater_boost').state == 'off'


@pytest.mark.asyncio
async def test_temperature_limit_and_hysteresis(heater):
    hass, _ = heater
    await permit(hass)
    hass.states.async_set('sensor.water_heater_temperature', '65')
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    hass.states.async_set('sensor.water_heater_temperature', '64')
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    hass.states.async_set('sensor.water_heater_temperature', '62')
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'on'


@pytest.mark.asyncio
async def test_sensor_loss_stops_owned_boost(heater):
    hass, _ = heater
    await permit(hass)
    hass.states.async_set('sensor.water_heater_temperature', 'unknown')
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'


@pytest.mark.asyncio
async def test_startup_reconciles_restored_boost_without_permission(heater):
    hass, _ = heater
    # Simulate restored relay/ownership before the startup trigger runs.
    hass.states.async_set('switch.water_heater', 'on')
    await hass.services.async_call('input_boolean', 'turn_on',
                                   {'entity_id': 'input_boolean.open_rec_heater_boost'}, blocking=True)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_START)
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
    assert hass.states.get('input_boolean.open_rec_heater_boost').state == 'off'


@pytest.mark.asyncio
async def test_manual_off_during_owned_boost_stays_off(heater):
    hass, _ = heater
    await permit(hass)
    hass.states.async_set('switch.water_heater', 'off')
    await settle(hass)
    await hass.services.async_call('automation', 'trigger', {'entity_id': CONTROLLER}, blocking=True)
    await settle(hass)
    assert hass.states.get('switch.water_heater').state == 'off'
