function requireCondition(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function requireAcknowledged(result, message) {
  requireCondition(result && result.acknowledged === true, message);
  return result;
}

const passedAssertions = [];
const passedAssertionIds = new Set();

function recordPass(assertionId) {
  requireCondition(
    /^[a-z0-9][a-z0-9._-]*$/.test(assertionId),
    "MongoDB assertion ID is not canonical: " + assertionId
  );
  requireCondition(
    !passedAssertionIds.has(assertionId),
    "MongoDB assertion ID was recorded twice: " + assertionId
  );
  passedAssertionIds.add(assertionId);
  passedAssertions.push({ id: assertionId, status: "pass" });
}

const database = db.getSiblingDB("dhi_contract");
const probe = database.probe;
const lifecycle = database.lifecycle_probe;
const lifecyclePhase = process.env.DHI_MONGODB_LIFECYCLE_PHASE;

requireCondition(
  lifecyclePhase === "initial" || lifecyclePhase === "restart",
  "MongoDB lifecycle phase must be exactly initial or restart"
);

const ping = database.runCommand({ ping: 1 });
const hello = db.hello();
requireCondition(
  ping.ok === 1 && hello.isWritablePrimary === true,
  "MongoDB application connection is not an authenticated writable primary"
);
recordPass("auth.application_ready");

requireCondition(
  process.env.DHI_MONGODB_WRONG_PASSWORD_REJECTED === "1",
  "MongoDB wrapper did not prove wrong-password rejection"
);
recordPass("auth.wrong_password_rejected");

requireCondition(
  hello.setName === "dhi-rs" &&
    typeof hello.logicalSessionTimeoutMinutes === "number" &&
    hello.logicalSessionTimeoutMinutes > 0,
  "MongoDB is not a session-capable member of the expected replica set"
);
recordPass("replication.transaction_capable");

const lifecycleDocuments = lifecycle.find({}).toArray();
if (lifecyclePhase === "initial") {
  const applicationCollections = database
    .getCollectionNames()
    .filter(name => name === "probe" || name === "lifecycle_probe");
  requireCondition(
    lifecycleDocuments.length === 0 && applicationCollections.length === 0,
    "MongoDB initial lifecycle phase did not start with empty application state"
  );
  print("MongoDB lifecycle marker is absent on the fresh data volume as expected");
} else {
  requireCondition(
    lifecycleDocuments.length === 1 &&
      lifecycleDocuments[0]._id === "mongodb-persistence-v1" &&
      lifecycleDocuments[0].expectedState === "mongodb-app-ok|2|0|0|12" &&
      Object.keys(lifecycleDocuments[0]).sort().join(",") === "_id,expectedState",
    "MongoDB lifecycle marker is inconsistent"
  );

  const persistedDocuments = probe.find({}).sort({ _id: 1 }).toArray();
  requireCondition(
    persistedDocuments.length === 2 &&
      persistedDocuments[0]._id === 1 &&
      persistedDocuments[0].value === "mongodb-app-ok" &&
      persistedDocuments[0].amount === 5 &&
      Object.keys(persistedDocuments[0]).sort().join(",") === "_id,amount,value" &&
      persistedDocuments[1]._id === 2 &&
      persistedDocuments[1].value === "committed-value" &&
      persistedDocuments[1].amount === 7 &&
      Object.keys(persistedDocuments[1]).sort().join(",") === "_id,amount,value",
    "MongoDB restart did not preserve the exact application document set"
  );

  const persistedAggregate = probe.aggregate([
    { $match: { _id: { $in: [1, 2] } } },
    { $group: { _id: null, count: { $sum: 1 }, total: { $sum: "$amount" } } }
  ]).toArray();
  requireCondition(
    persistedAggregate.length === 1 &&
      persistedAggregate[0].count === 2 &&
      persistedAggregate[0].total === 12,
    "MongoDB restart returned an unexpected persisted aggregate"
  );

  const persistedIndexes = probe.getIndexes();
  const persistedIndex = persistedIndexes.find(index => index.name === "value_unique");
  requireCondition(
    persistedIndexes.length === 2 &&
      persistedIndexes.some(index => index.name === "_id_" && index.key._id === 1) &&
      persistedIndex &&
      persistedIndex.unique === true &&
      persistedIndex.key.value === 1,
    "MongoDB restart did not preserve the exact unique-index state"
  );
  print("MongoDB verified the durable lifecycle marker, index, and application state before cleanup");
}
recordPass("persistence.lifecycle_state");

requireAcknowledged(probe.deleteMany({}), "MongoDB cleanup was not acknowledged");
const firstIndex = probe.createIndex(
  { value: 1 },
  { unique: true, name: "value_unique" }
);
const secondIndex = probe.createIndex(
  { value: 1 },
  { unique: true, name: "value_unique" }
);
requireCondition(
  firstIndex === "value_unique" && secondIndex === "value_unique",
  "MongoDB unique-index creation returned an unexpected name"
);

const insertResult = requireAcknowledged(
  probe.insertOne({ _id: 1, value: "initial-value", amount: 2 }),
  "MongoDB initial insert was not acknowledged"
);
const updateResult = requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" }, $inc: { amount: 3 } }
), "MongoDB update was not acknowledged");
const firstUpsert = requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" } },
  { upsert: true }
), "MongoDB first idempotent upsert was not acknowledged");
const secondUpsert = requireAcknowledged(probe.updateOne(
  { _id: 1 },
  { $set: { value: "mongodb-app-ok" } },
  { upsert: true }
), "MongoDB second idempotent upsert was not acknowledged");

const updated = probe.findOne({ _id: 1 });
requireCondition(
  insertResult.insertedId === 1 &&
    updateResult.matchedCount === 1 &&
    updateResult.modifiedCount === 1 &&
    updated &&
    updated.value === "mongodb-app-ok" &&
    updated.amount === 5,
  "MongoDB update/find assertion returned unexpected state");
recordPass("crud.insert_update_find");

requireCondition(
  firstUpsert.matchedCount === 1 &&
    firstUpsert.upsertedCount === 0 &&
    secondUpsert.matchedCount === 1 &&
    secondUpsert.upsertedCount === 0 &&
    probe.countDocuments({ _id: 1 }) === 1,
  "MongoDB idempotent upserts changed the application document cardinality"
);
recordPass("crud.idempotent_upsert");

let duplicateRejected = false;
try {
  probe.insertOne({ _id: 99, value: "mongodb-app-ok", amount: 99 });
} catch (error) {
  duplicateRejected = error.code === 11000;
}
requireCondition(duplicateRejected, "MongoDB unique index accepted a duplicate value");
recordPass("index.unique");
print("MongoDB unique index rejected duplicate data as expected");

const session = db.getMongo().startSession();
try {
  const sessionDatabase = session.getDatabase("dhi_contract");

  session.startTransaction();
  requireAcknowledged(sessionDatabase.probe.insertOne({
    _id: 2,
    value: "committed-value",
    amount: 7
  }), "MongoDB committed-transaction insert was not acknowledged");
  session.commitTransaction();

  session.startTransaction();
  requireAcknowledged(sessionDatabase.probe.insertOne({
    _id: 3,
    value: "rolled-back-value",
    amount: 11
  }), "MongoDB aborted-transaction insert was not acknowledged");
  session.abortTransaction();
} finally {
  session.endSession();
}

const deleteFixture = requireAcknowledged(
  probe.insertOne({ _id: 4, value: "delete-me", amount: 13 }),
  "MongoDB delete fixture insert was not acknowledged"
);
const deleteResult = requireAcknowledged(
  probe.deleteOne({ _id: 4 }),
  "MongoDB delete was not acknowledged"
);

const aggregate = probe.aggregate([
  { $match: { _id: { $in: [1, 2] } } },
  { $group: { _id: null, count: { $sum: 1 }, total: { $sum: "$amount" } } }
]).toArray();
requireCondition(
  aggregate.length === 1 && aggregate[0].count === 2 && aggregate[0].total === 12,
  "MongoDB aggregation returned unexpected state"
);
requireCondition(probe.countDocuments({ _id: 2 }) === 1,
  "MongoDB committed transaction state is missing");
recordPass("transaction.commit");
requireCondition(probe.countDocuments({ _id: 3 }) === 0,
  "MongoDB aborted transaction state was persisted");
recordPass("transaction.abort");
requireCondition(
  deleteFixture.insertedId === 4 &&
    deleteResult.deletedCount === 1 &&
    probe.countDocuments({ _id: 4 }) === 0,
  "MongoDB delete assertion failed");
recordPass("crud.delete");
recordPass("query.aggregate");

let administrationDenied = false;
try {
  const forbidden = db.getSiblingDB("admin").runCommand({
    createUser: "dhi_forbidden",
    pwd: "not-used",
    roles: []
  });
  administrationDenied = forbidden.ok !== 1 && forbidden.code === 13;
} catch (error) {
  administrationDenied = error.code === 13 || error.codeName === "Unauthorized";
}
requireCondition(administrationDenied,
  "MongoDB application user unexpectedly obtained user-administration privileges");
recordPass("authorization.user_admin_denied");
print("MongoDB application user was denied user administration as expected");

const lifecycleUpdate = requireAcknowledged(lifecycle.updateOne(
  { _id: "mongodb-persistence-v1" },
  { $set: { expectedState: "mongodb-app-ok|2|0|0|12" } },
  { upsert: true }
), "MongoDB lifecycle-marker upsert was not acknowledged");

const finalLifecycleDocuments = lifecycle.find({}).toArray();
const finalDocuments = probe.find({}).sort({ _id: 1 }).toArray();
requireCondition(
  lifecycleUpdate.matchedCount + lifecycleUpdate.upsertedCount === 1 &&
    finalLifecycleDocuments.length === 1 &&
    finalLifecycleDocuments[0]._id === "mongodb-persistence-v1" &&
    finalLifecycleDocuments[0].expectedState === "mongodb-app-ok|2|0|0|12" &&
    finalDocuments.length === 2 &&
    finalDocuments[0]._id === 1 &&
    finalDocuments[0].value === "mongodb-app-ok" &&
    finalDocuments[0].amount === 5 &&
    finalDocuments[1]._id === 2 &&
    finalDocuments[1].value === "committed-value" &&
    finalDocuments[1].amount === 7,
  "MongoDB final application and lifecycle state is not exact"
);
recordPass("state.final_summary");

print(
  "MongoDB authenticated replica-set application contract passed: " +
    "phase=" + lifecyclePhase + " state=mongodb-app-ok|2|0|0|12"
);

print("DHI_ASSERTION_SUMMARY " + JSON.stringify({
  assertions: passedAssertions,
  counts: { fail: 0, pass: passedAssertions.length },
  outcome: "pass",
  schemaVersion: 1,
  suite: "mongodb"
}));
