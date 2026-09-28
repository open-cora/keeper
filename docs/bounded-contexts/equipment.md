# Equipment

Equipment is the bounded context that answers one question: what hardware does this system know about, and what state was it last reported in.

It holds one aggregate. The Device is one piece of hardware this system holds a record of: where its control system publishes it, a label for it, and what it was last reported doing. Six operations.

The hardware itself lives outside, at a beamline, driven by whatever **control system** the deployment runs. This context holds a record of what that control system publishes and what somebody said about it, never the hardware and never its readings.

## What a Device is

One piece of hardware, and three facts about it.

```
   Device
     id            a UUID minted when the device is added
     external_ref  where the control system publishes it
     name          a label this system wrote, for a person to read
     status        Available, Faulted or Retired
```

The status is not a field anybody sets. It is worked out from the events on the stream each time the device is read, so it cannot disagree with the history behind it.

## Why the address is the identity

A device's record carries an **external reference**, the same open-scheme `(scheme, value)` pair a dataset carries, and it is required. That is a measured decision rather than a preference, and the measurement is in a spike.

The spike built the same motor twice, from two startup profiles, against one control system. It answered to two different names at once, both connected, both correct, with nothing anywhere recording that they were one device. A control library's name for a device is an argument passed at construction, so it survives exactly as long as the process that chose it and changes whenever somebody edits a profile.

The facility-side label is no better. The one description field the spike found was served empty and writable by any client.

So the address is what two independent clients will agree on, and nothing else is. Note what that concedes: an address is a deployment's configuration, and a control system can be rebuilt under a new one, so it is stable in practice rather than guaranteed. It is still the best available, and better than the case a sibling spike found next door, where the closest thing to a run's identity was an output file path.

**Nothing enforces that an address is unique across devices.** An event-sourced aggregate has no consistency boundary spanning its siblings, so registering one motor twice makes two records and nothing notices. That gap matters more here than it does for a dataset: a caller resolving a dataset is reading, and a caller resolving a device is about to write to whatever comes back. What this context does about it is refuse to hide it. The listing returns both, and an adapter that finds two has to decide rather than be handed one at random.

## What the label is, and the one rule on it

`name` is this system's own label, authored here. It exists because a register that lists addresses and nothing else is not usable by a person, and it is honest because the record makes the fact rather than reporting one, so it cannot be wrong about the world.

**An adapter must not copy the facility's description field into it.** That field is free text somebody typed at a beamline, and free text swept in from outside is how a person's name reaches a table that cannot be edited. The same rule, for the same reason, keeps a message off a broken step and a reason off a deactivated actor.

On the event the field is `device_name` rather than `name`, qualified the way an operation's is, because the personal-data check reads field names and cannot tell a piece of hardware's label from a person's.

## The status, and what it does not claim

Three values, derived in the fold from which events the stream carries and stored nowhere, so the status cannot disagree with the history behind it.

```
   Available   registered, and nothing stands against it
   Faulted     a fault was reported and nothing has recovered it
   Retired     this system no longer counts this device
```

The three split by voice, and that split is the shape of the whole aggregate. Available and Retired are this system's own bookkeeping. Faulted is the only one that is a claim about the world.

**Available does not mean the device works.** It means no fault has been reported and none stands. That is the same caveat a run's `Running` carries, and here it is weaker, for three reasons the spikes measured rather than assumed:

- A fault is delivered at most once, to whoever happened to be subscribed when it happened. A reporter that restarted was not.
- A reporter's cached view of an alarm outlives the device it describes. With the control system stopped, reading the value fails loudly and reading the alarm returns the last number seen, silently, with nothing in the call saying it is stale.
- Hardware outlives the thing driving it, and no ending is emitted on any path. That one is a spike's finding rather than this context's spike, and it closes the same door from the third side.

Together those say what a reporter has to be: something that reports faults it saw, not something whose silence means anything. A device nobody watched reads as available forever, the way a run nobody ended reads as running.

## What a fault is

The reporter's judgement, and not a value copied through.

What a control system publishes is an alarm severity. An alarm is not a fault: the routine ones are routine, and a device in one is usually still usable. Deciding that a given severity amounts to a fault is exactly the call a reporter already makes when it picks one of an engine run's three terminals.

So the severity does not reach the record. On the record it would invite a later reader to re-derive the judgement from a number, which is a claim about hardware health this system never made. Nothing on a transition carries a reason either, and who reported it is on the envelope where every other command's principal is.

## Why recovery and not restoration

The pair is fault and recovery, which is what an operator says and what alerting tools mean by it. Restoring is something somebody does, and usually nobody did: the condition ended, the camera cooled, the alarm cleared.

Retiring, likewise, rather than withdrawing. Withdrawing is what happens to a proposal in this tree, by the party that made it, and the [Glossary](../reference/glossary.md) defines each term once. Retiring is the ordinary word for taking a thing out of an active register, which is what this is.

**Retiring is not deleting.** The stream stays, the history stays readable, and a reader asking what this device did last year still gets an answer. What changes is that the system stops counting it as present. It also does not claim the hardware left the beamline: that is a different fact, at a different moment, that this system was not present for and does not model.

A faulted device can be retired without being recovered first. That is the ordinary way a broken thing leaves a register, not an edge case.

## Which commands may carry a time

R8 in [Naming](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one) runs between commands on one stream here, and the answer follows the voice split above:

```
   register_device   no time     enrolling is an act performed here
   fault_device      a time      it happened at a beamline
   recover_device    a time      so did this
   retire_device     no time     the register stops counting it here, now
```

`register_device` is the one worth arguing about, because its nearest neighbour goes the other way. `register_dataset` takes a caller's time, since data was written somewhere at a knowable moment and a backfill out of an archive would otherwise date every dataset to the afternoon of the import. Enrolling a device has no such moment. When the hardware was installed is not something any adapter can supply, and the only act this system can date is its own enrolling. So it sits beside `register_actor` rather than beside `register_dataset`.

Every event carries an `occurred_at` regardless, because the envelope needs one. What differs is where it comes from.

## What this context does not hold

Each of these is a decision, and the first three are backed by what the spike measured rather than by a guess.

**No readings.** One device publishes tens of signals that move continuously. An append-only log is the wrong home for them, and the right home is a time-series store this system holds at most a reference to.

**No configuration.** Seven of the thirteen configuration values on one simulated station were a named person, all of them one call away. That makes the easy implementation the dangerous one, and the spike also found the obvious redaction rule to be wrong: matching on the word `user` also drops a motor's user coordinate offset, which is calibration.

**No intervals.** "Was this device faulted while that run was going" is not answerable here, and the absence is deliberate. Faults are point events with a time. Deriving a span from two of them reads as precision while resting on a clear nobody may have seen, and one missed clear extends the span forever.

**No tree.** Where one device stops is a client-side composition: thirty signals under one station, arranged by classes a profile author wrote, while the control system publishes a flat namespace of addresses and has never heard of the station. So what is registered is the thing the address names.

## What it reaches across for

Nothing, in either direction, and it is the first context in this tree with no cross-context door at all.

A device is not registered by a run, not faulted by one, and not cited by one. Every other context has an entry in `tach.toml` naming a sibling's aggregates; this one's dependency list is its own aggregates and the two layers every module gets.

That absence is the model rather than a context waiting to be finished. Whether a run touched a faulted device is a question about both, and the place to answer it is whichever context grows a reason to ask, with a join it writes itself.

## The operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Add a device | `POST /devices` | `register_device` | `201` with the new id |
| Find devices | `GET /devices` | `list_devices` | `200` with a page of devices |
| Read one back | `GET /devices/{device_id}` | `get_device` | `200` with the device |
| Say it has gone wrong | `POST /devices/{device_id}/fault` | `fault_device` | `204` |
| Say it is working again | `POST /devices/{device_id}/recover` | `recover_device` | `204` |
| Take it out of service | `POST /devices/{device_id}/retire` | `retire_device` | `204` |

A verb in the path rather than a `PATCH` with a status field. The two are not equivalent: a `PATCH` says what the device should look like afterwards and invites a caller to set the status at will, while each of these names one transition the domain either allows or refuses. The status is derived from the stream in any case, so there is nothing for a `PATCH` to write. Retirement is a `POST` rather than a `DELETE` for the same reason the word is retire: the record is not going anywhere.

Every one is published on the MCP surface, which is what every context here does with every slice it has. What is worth noting is that the default costs nothing in this one. The agent and the reporter are the same kind of client, something watching a beamline, and both halves of what it does are in this context: resolve an address, then say what happened at it.

## What the stream holds

There is no devices table. A device is worked out by replaying its events every time it is read.

```
   DeviceRegistered   device_id, external_ref_scheme, external_ref_value,
                      device_name, occurred_at
   DeviceFaulted      device_id, occurred_at
   DeviceRecovered    device_id, occurred_at
   DeviceRetired      device_id, occurred_at
```

Only the first carries anything beyond an id and a time, and that is the point. A fault says that something went wrong and when, and nothing about what: no severity, no message, no reason. Recovery is its own event rather than a flag going back, which is what makes the history readable. How many times a device broke and came back, and when, exists only because each change left its own row.

The label is stored as `device_name` rather than `name`. The check that keeps personal data out of events reads field names, and a bare `name` looks the same to it whether it labels a motor or a person.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidDeviceNameError` | 400 | The label is empty, too long, or not text. |
| `InvalidDeviceFilterError` | 400 | The listing was asked for a status that is not one of the three. |
| `UnauthorizedError` | 403 | We know who is asking and they may not. Different from 401, where we do not know. |
| `DeviceNotFoundError` | 404 | The id names no device. |
| `DeviceAlreadyExistsError` | 409 | Adding was aimed at an id that already has a history. |
| `DeviceCannotBeFaultedError` | 409 | Already faulted, or retired. |
| `DeviceCannotBeRecoveredError` | 409 | Not faulted, or retired. |
| `DeviceCannotBeRetiredError` | 409 | Already retired. |
| `ConcurrencyError` | 409 | The device changed between the read and the write. Read it again and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key came back with a different body, so no saved answer can be right. |

Repeating a change is refused rather than quietly working. Two people each reporting what they think is a new fault should not both be told they reported it; one of them is looking at a stale view.

Retired refuses all three transitions, not just retirement. A device this system has stopped counting is not somewhere a fault can be reported, and the three deciders all ask the same question of the status rather than each carrying their own copy of what terminal means.

Adding a device takes a retry key, so sending the same one twice returns the first answer instead of making a second record. The three transitions do not take one: a repeat is already refused by the rules above, so a key would buy a friendlier status code rather than stop a second write.

## The listing, and why it has two filters

`GET /devices` filters by address and by status, where the sibling listings have one filter each and argue against adding more. Both of these have a caller.

The address filter is what makes the context usable by an adapter at all. A reporter holds the address it is subscribed to and nothing else, because ids are minted here, so resolving one to an id is its first call and every fault it later reports depends on it. That is the same resolution an agent already performs against the run listing before it can record what took its proposal.

The status filter is the operator's question, and the one the context exists to answer: what is broken right now.

A row carries every field the single read has, plus two timestamps. That is unlike the three summaries beside it, each of which drops a field for being unbounded. A device has none: the label is bounded and everything else is an id, a word or a time. So a caller that finds what it wanted in a page needs no second call.

## Where the code is

```
   apps/keeper/src/keeper/equipment/
     aggregates/device/      the fields, the events, and how one is read back
     features/
       register_device/      one directory per operation
       fault_device/
       recover_device/
       retire_device/
       get_device/           a read, so no decision to make
       list_devices/
     projections/            the table the listing reads
     adapters/               how that table is queried
     routes.py               HTTP mounting, and which error becomes which status
     tools.py                MCP tool registration
     wire.py                 which operation gets a retry key, which gets tracing
```

Each write is a slice of its own: its own command, its own decision, its own handler, its own route and tool. Slices do not import each other, so a seventh operation is a new directory rather than an edit to six existing ones.

## What is not here yet

**Two devices at one address.** Nothing stops it. Records are independent of each other, so adding the same motor twice makes two of them and nothing notices. That matters more here than elsewhere, because somebody resolving an address is usually about to write to whatever comes back. The listing returns both rather than picking one, so a caller that finds two has to decide.

**No way to ask what was broken at a given moment.** Faults are points in time, and turning two of them into a span would read as precision while resting on a clear that nobody may have sent. One missed clear stretches the span forever. See [What this context does not hold](#what-this-context-does-not-hold).

**Nothing watches.** A fault only reaches the record because something reported it, so a device nobody is watching reads as available forever. That is a property of the system rather than a gap in this context, and the page says it in [The status, and what it does not claim](#the-status-and-what-it-does-not-claim).
