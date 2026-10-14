/* Saved-evidence entry. The host owns packages; the backend owns revisions and approval. */
(function () {
  'use strict';
  var dom = window.SwReviewDom;

  function create(options) {
    var ui = {};
    var ids = ['prepare', 'selection', 'refresh', 'state', 'entry', 'target', 'kind', 'id', 'text',
      'requirement-fields', 'force-fields', 'magnitude', 'unit', 'unknown', 'frame', 'provenance',
      'assumptions', 'save', 'new', 'actor', 'records', 'review'];
    ids.forEach(function (id) { ui[id] = document.getElementById('context-' + id); });
    var panel = document.getElementById('engineering-context');
    var prepared = null;
    var snapshot = null;
    var pending = false;
    var editingRecordId = null;
    var available = false;
    var selectionAvailable = false;
    var epoch = 0;

    function say(text) { ui.state.textContent = text || ''; }
    function refreshControls() {
      var blocked = pending || options.busy() || !options.ready();
      var model = options.document();
      ui.prepare.disabled = blocked || !model || !/\.sld(?:prt|asm)$/i.test(model.path || '');
      ui.selection.disabled = blocked || !prepared || !snapshot || !selectionAvailable;
      ui.refresh.disabled = blocked || !prepared;
      ui.save.disabled = blocked || !snapshot;
      ui.new.disabled = blocked || !snapshot;
      ui.review.disabled = blocked || !snapshot || !snapshot.records.length;
      var confirms = ui.records.querySelectorAll('button');
      for (var i = 0; i < confirms.length; i++) {
        confirms[i].disabled = blocked || !snapshot || confirms[i].getAttribute('data-unavailable') === 'true';
      }
    }
    function invalidate(message) {
      epoch++;
      prepared = null;
      snapshot = null;
      editingRecordId = null;
      ui.save.textContent = 'Save new draft input';
      pending = false;
      ui.entry.hidden = true;
      newDraft();
      dom.clear(ui.target);
      dom.clear(ui.frame);
      dom.clear(ui.records);
      say(message || 'Extract saved evidence to add engineering inputs.');
      refreshControls();
    }
    function path(suffix) {
      return '/engineering-context/' + encodeURIComponent(prepared.run_id) + (suffix || '');
    }
    function operation(action) {
      if (pending || options.busy()) return Promise.resolve();
      var activeEpoch = epoch;
      pending = true;
      refreshControls();
      return Promise.resolve().then(function () { return action(activeEpoch); }).catch(function (error) {
        if (activeEpoch !== epoch) return;
        if (error.errorClass === 'EngineeringContextConflict') {
          snapshot = null;
          editingRecordId = null;
          ui.entry.hidden = true;
          dom.clear(ui.records);
          say((error.message || 'The saved context changed.') + ' Refresh saved inputs before continuing.');
        } else if (error.errorClass === 'ContextExpired' || error.errorClass === 'UnknownEngineeringContextRun') {
          invalidate(error.message);
        } else say(error.message || 'Engineering context could not be updated.');
      }).then(function () {
        if (activeEpoch === epoch) { pending = false; refreshControls(); }
      });
    }
    function inspect(activeEpoch) {
      return options.call(path(), 'GET').then(function (data) {
        if (activeEpoch !== epoch) return;
        if (!data || data.package_sha256 !== prepared.package_sha256 || !data.initialized) {
          invalidate('The saved evidence changed. Extract context evidence again.');
          return;
        }
        snapshot = data;
        renderTargets();
        renderRecords();
        ui.entry.hidden = false;
        say('Saved context revision ' + data.revision + '. Current model state has not been verified.'
          + (data.targets_omitted ? ' ' + data.targets_omitted + ' saved targets omitted from this list; try model selection.' : ''));
      });
    }
    function addOption(select, value, label) {
      var option = dom.el('option', '', label);
      option.value = value;
      select.appendChild(option);
    }
    function targetLabel(target) {
      return (target.label || target.entity_id) + ' (' + target.kind + ', '
        + (target.configuration || 'configuration unknown')
        + (target.component_id ? ', occurrence ' + target.component_id : '') + ')';
    }
    function renderTargets() {
      var previous = ui.target.value;
      dom.clear(ui.target);
      (snapshot.targets || []).forEach(function (target, index) {
        addOption(ui.target, String(index), targetLabel(target));
      });
      if (previous && ui.target.querySelector('option[value="' + previous + '"]')) ui.target.value = previous;
      var frame = ui.frame.value;
      dom.clear(ui.frame);
      addOption(ui.frame, '', 'Root model coordinate frame');
      (snapshot.targets || []).forEach(function (target) {
        if (target.kind === 'component') addOption(ui.frame, target.entity_id, targetLabel(target));
      });
      ui.frame.value = frame;
      if (ui.frame.selectedIndex < 0) ui.frame.value = '';
    }
    function vector(prefix) {
      var values = ['x', 'y', 'z'].map(function (axis) {
        return document.getElementById('context-' + prefix + axis).value.trim();
      });
      if (values.every(function (value) { return value === ''; })) return null;
      if (values.some(function (value) { return value === ''; })) throw new Error('Enter all three vector values or leave all blank.');
      return values.map(function (value) {
        var number = Number(value);
        if (!isFinite(number)) throw new Error('Vector values must be finite numbers.');
        return number;
      });
    }
    function setVector(prefix, values) {
      ['x', 'y', 'z'].forEach(function (axis, index) {
        document.getElementById('context-' + prefix + axis).value = values ? values[index] : '';
      });
    }
    function inputBody() {
      var target = snapshot.targets[Number(ui.target.value)];
      if (!target) throw new Error('Choose a target in the saved evidence.');
      var body = {
        expected_head: snapshot.head_digest, record_id: ui.id.value.trim(), kind: target.kind,
        entity_id: target.entity_id, component_id: target.component_id || null,
        provenance_kind: ui.provenance.value,
        assumptions: ui.assumptions.value.split(/\r?\n/).filter(function (line) { return line.trim(); })
      };
      var exists = snapshot.records.some(function (row) { return row.record.record_id === body.record_id; });
      if (exists && editingRecordId !== body.record_id) {
        throw new Error('An input with this name exists. Choose Edit on its saved preview or use another name.');
      }
      if (ui.kind.value === 'requirement') body.text = ui.text.value;
      else {
        if (target.kind === 'document') throw new Error('Choose a component or face for a total force.');
        var magnitude = ui.magnitude.value.trim();
        body.magnitude = magnitude === '' ? null : Number(magnitude);
        if (body.magnitude !== null && (!isFinite(body.magnitude) || body.magnitude < 0)) {
          throw new Error('Force magnitude must be a finite nonnegative number.');
        }
        body.unit = ui.unit.value;
        body.direction = vector('d');
        body.unknown_reason = body.magnitude === null ? ui.unknown.value : null;
        body.frame_component_id = ui.frame.value || null;
        body.point_m = vector('p');
      }
      return body;
    }
    function switchInput() {
      var force = ui.kind.value === 'applied_force';
      ui['force-fields'].hidden = !force;
      ui['requirement-fields'].hidden = force;
    }
    function edit(row) {
      var record = row.record;
      editingRecordId = record.record_id;
      ui.save.textContent = 'Save revised input';
      var index = (snapshot.targets || []).findIndex(function (target) {
        return target.kind === record.anchor.kind && target.entity_id === record.anchor.entity_id
          && (target.component_id || null) === (record.anchor.component_id || null);
      });
      if (index < 0) {
        snapshot.targets.push(record.anchor);
        renderTargets();
        index = snapshot.targets.length - 1;
      }
      ui.target.value = String(index);
      ui.kind.value = record.kind;
      ui.id.value = record.record_id;
      ui.text.value = record.text || '';
      ui.provenance.value = record.provenance.kind;
      ui.assumptions.value = (record.assumptions || []).join('\n');
      if (record.kind === 'applied_force') {
        ui.magnitude.value = record.magnitude.value === null ? '' : record.magnitude.value;
        ui.unit.value = record.magnitude.unit;
        ui.unknown.value = record.magnitude.reason || '';
        setVector('d', record.direction);
        setVector('p', record.point_m);
        ui.frame.value = record.frame && record.frame.component_id || '';
      }
      switchInput();
    }
    function newDraft() {
      editingRecordId = null;
      var prefix = ui.kind.value === 'applied_force' ? 'force:' : 'requirement:';
      var index = 1;
      while (snapshot && snapshot.records.some(function (row) { return row.record.record_id === prefix + index; })) index++;
      ui.id.value = prefix + index;
      ui.text.value = '';
      ui.magnitude.value = '';
      ui.unknown.value = '';
      ui.frame.value = '';
      ui.provenance.value = 'engineer';
      ui.assumptions.value = '';
      setVector('d', null);
      setVector('p', null);
      ui.save.textContent = 'Save new draft input';
    }
    function renderRecords() {
      dom.clear(ui.records);
      (snapshot.records || []).forEach(function (row) {
        var record = row.record;
        var card = dom.el('article', 'context-record');
        var publicRecord = typeof record.record_id === 'string' && record.record_id.length > 0;
        card.appendChild(dom.el('h3', '', (publicRecord ? record.record_id : 'Saved input') + ' — revision ' + record.revision));
        card.appendChild(dom.field('Target', targetLabel(record.anchor)));
        card.appendChild(dom.field('Decision', row.decision));
        card.appendChild(dom.field('Evidence', row.binding.status === 'matched_snapshot'
          ? 'Matches saved evidence' : 'Needs review against saved evidence'));
        if (record.kind === 'requirement') card.appendChild(dom.field('Requirement', record.text));
        else {
          card.appendChild(dom.field('Magnitude', record.magnitude.state === 'known'
            ? String(record.magnitude.value) + ' ' + record.magnitude.unit
            : 'Unknown: ' + record.magnitude.reason));
          card.appendChild(dom.field('Direction', record.direction ? record.direction.join(', ') : 'Unknown'));
          card.appendChild(dom.field('Frame', record.frame ? (record.frame.label || record.frame.frame_id) : 'Unknown'));
          card.appendChild(dom.field('Application', record.application === 'face_total' ? 'Total force on face' : 'Total force on component'));
          card.appendChild(dom.field('Application point (m)', record.point_m ? record.point_m.join(', ') : 'Not specified'));
          card.appendChild(dom.field('Distribution', 'Unspecified'));
          if (record.frame && record.frame.transform) {
            var matrix = record.frame.transform;
            ['X', 'Y', 'Z'].forEach(function (axis, column) {
              card.appendChild(dom.field('Frame ' + axis + ' in root', [matrix[0][column], matrix[1][column], matrix[2][column]].join(', ')));
            });
            card.appendChild(dom.field('Frame origin in root (m)', [matrix[0][3], matrix[1][3], matrix[2][3]].join(', ')));
          }
          if (row.resolved_force) {
            card.appendChild(dom.field('Root force (N)', row.resolved_force.vector_n.join(', ')));
            if (row.resolved_force.point_m) card.appendChild(dom.field('Root application point (m)', row.resolved_force.point_m.join(', ')));
          }
        }
        var sources = { engineer: 'Engineer', ai_proposal: 'AI proposal', extracted: 'Extracted', catalogue: 'Catalogue', derived: 'Derived', unknown: 'Unknown' };
        card.appendChild(dom.field('Source', sources[record.provenance.kind] || 'Unknown'));
        if (record.assumptions.length) card.appendChild(dom.field('Assumptions', record.assumptions.join('; ')));
        var editButton = dom.button('Edit saved input', 'context-edit');
        editButton.setAttribute('data-unavailable', String(!publicRecord));
        editButton.addEventListener('click', function () { edit(row); });
        card.appendChild(editButton);
        var confirm = dom.button('Confirm these saved inputs', 'context-confirm');
        var complete = record.kind === 'requirement' || (record.magnitude.state === 'known' && record.direction && record.frame);
        confirm.setAttribute('data-unavailable', String(!publicRecord || row.binding.needs_review || !complete || row.decision === 'confirmed'));
        confirm.addEventListener('click', function () {
          if (!ui.actor.value.trim()) { say('Enter your name before confirming the displayed saved inputs.'); return; }
          var shownHead = snapshot.head_digest;
          operation(function (activeEpoch) {
            return options.call(path('/confirm'), 'POST', {
              expected_head: shownHead, record_id: record.record_id, actor: ui.actor.value.trim(),
              expected_record_digest: row.record_digest, expected_dependency_digest: row.dependency_digest
            }).then(function () { if (activeEpoch === epoch) return inspect(activeEpoch); });
          });
        });
        card.appendChild(confirm);
        ui.records.appendChild(card);
      });
    }
    ui.prepare.addEventListener('click', function () {
      invalidate();
      operation(function (activeEpoch) {
        return options.send('context.prepare', {}).then(function (payload) {
          if (activeEpoch !== epoch) return;
          prepared = payload;
          return options.call(path('/init'), 'POST', {}).then(function () {
            if (activeEpoch === epoch) return inspect(activeEpoch);
          });
        });
      });
    });
    ui.refresh.addEventListener('click', function () { operation(inspect); });
    ui.selection.addEventListener('click', function () {
      operation(function (activeEpoch) {
        return options.send('context.selection', {
          run_id: prepared.run_id, package_sha256: prepared.package_sha256
        }).then(function (observation) {
          if (activeEpoch !== epoch) return;
          if (observation.status !== 'matched_saved_target' || observation.package_sha256 !== prepared.package_sha256) {
            say('Selection could not be matched. Select one saved, resolved component or face, or choose a saved target.');
            return;
          }
          var target = { kind: observation.kind, entity_id: observation.entity_id,
            component_id: observation.component_id, document_id: observation.document_id,
            configuration: observation.configuration, label: observation.display_name || observation.entity_id };
          var index = snapshot.targets.findIndex(function (saved) {
            return saved.kind === target.kind && saved.entity_id === target.entity_id
              && (saved.component_id || null) === (target.component_id || null);
          });
          if (index < 0) { snapshot.targets.push(target); renderTargets(); index = snapshot.targets.length - 1; }
          ui.target.value = String(index);
          say('Selected saved target filled in. Current geometry has not been verified; selection testing is still required.');
        });
      });
    });
    ui.save.addEventListener('click', function () {
      operation(function (activeEpoch) {
        var body = inputBody();
        var endpoint = ui.kind.value === 'requirement' ? '/requirement' : '/force';
        return options.call(path(endpoint), 'POST', body).then(function () {
          if (activeEpoch === epoch) {
            editingRecordId = body.record_id;
            ui.save.textContent = 'Save revised input';
            return inspect(activeEpoch);
          }
        });
      });
    });
    ui.review.addEventListener('click', function () {
      if (!snapshot) return;
      var attachment = { run_id: prepared.run_id, context_id: snapshot.context_id,
        head_digest: snapshot.head_digest, package_sha256: prepared.package_sha256 };
      operation(function () { return options.startReview(attachment).then(function () { invalidate(); }); });
    });
    ui.new.addEventListener('click', newDraft);
    ui.kind.addEventListener('change', function () {
      switchInput();
      if (!editingRecordId && /^(requirement|force):[0-9]+$/.test(ui.id.value)) newDraft();
    });
    switchInput();
    invalidate();
    return {
      invalidate: invalidate, refreshControls: refreshControls,
      configure: function (enabled, canSelect) {
        available = enabled === true;
        selectionAvailable = canSelect === true;
        panel.hidden = !available;
        refreshControls();
      }
    };
  }
  window.SwReviewEngineeringContext = { create: create };
})();
