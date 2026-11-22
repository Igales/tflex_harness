using System;
using TFlex;
using TFlex.Model;
using TFlex.Model.Model3D;

namespace ParametricGuideWheel
{
    public class Macro
    {
        private const string Prefix = "WH_";
        private const string FirstName = "WH 01 Сердцевина";
        private const string FinalName = "WH 13 Колесо - итоговое тело";

        public static void Run()
        {
            Document doc = Application.ActiveDocument;
            if (doc == null) return;

            bool editing = false;
            string step = "Проверка документа";
            string endResultText = "EndChanges ещё не вызван";

            try
            {
                if (doc.GetObjectByName(FirstName) != null)
                {
                    throw new InvalidOperationException(
                        "В документе уже есть операции колеса. " +
                        "Запустите макрос в новом пустом 3D-документе.");
                }

                doc.BeginChanges("Колесо с двумя ребордами");
                editing = true;

                step = "Создание основных параметров";

                // =====================================================
                // ОСНОВНЫЕ ПАРАМЕТРЫ. Все линейные размеры — в миллиметрах.
                //
                // Это демонстрационный аналог направляющего колеса:
                // прямоугольная наружная канавка, две реборды,
                // ступица, две торцевые выборки и сквозное отверстие.
                //
                // Для изменения модели в новом документе меняйте
                // значения во втором числовом аргументе ниже.
                //
                // Если переменная уже существует, используется её
                // текущее значение, а не указанное начальное.
                // =====================================================

                Input(doc, "DOuter", 56.0,
                    "Наружный диаметр реборд");

                Input(doc, "DTrack", 46.0,
                    "Диаметр дна наружной канавки");

                Input(doc, "DPocket", 42.0,
                    "Наружный диаметр торцевых кольцевых выборок");

                Input(doc, "DHub", 18.0,
                    "Наружный диаметр ступицы");

                Input(doc, "DBore", 12.0,
                    "Диаметр сквозного осевого отверстия");

                Input(doc, "Width", 16.0,
                    "Ширина обода по наружным торцам реборд");

                Input(doc, "HubWidth", 20.0,
                    "Полная осевая длина ступицы");

                Input(doc, "GrooveWidth", 12.0,
                    "Ширина наружной канавки между ребордами");

                Input(doc, "WebWidth", 12.0,
                    "Толщина диска между торцевыми выборками");

                Input(doc, "ToolExtra", 2.0,
                    "Выход режущих инструментов за торцы");

                step = "Чтение и проверка параметров";

                double dOuter = Value(doc, "DOuter");
                double dTrack = Value(doc, "DTrack");
                double dPocket = Value(doc, "DPocket");
                double dHub = Value(doc, "DHub");
                double dBore = Value(doc, "DBore");

                double width = Value(doc, "Width");
                double hubWidth = Value(doc, "HubWidth");
                double grooveWidth = Value(doc, "GrooveWidth");
                double webWidth = Value(doc, "WebWidth");
                double extra = Value(doc, "ToolExtra");

                if (!(dBore < dHub &&
                      dHub < dPocket &&
                      dPocket < dTrack &&
                      dTrack < dOuter))
                {
                    throw new InvalidOperationException(
                        "Требуется: DBore < DHub < DPocket " +
                        "< DTrack < DOuter.");
                }

                if (grooveWidth >= width)
                {
                    throw new InvalidOperationException(
                        "GrooveWidth должна быть меньше Width.");
                }

                if (webWidth >= width)
                {
                    throw new InvalidOperationException(
                        "WebWidth должна быть меньше Width.");
                }

                if (hubWidth < width)
                {
                    throw new InvalidOperationException(
                        "HubWidth должна быть не меньше Width.");
                }

                // =====================================================
                // РАСЧЁТ ПРОИЗВОДНЫХ РАЗМЕРОВ В C#.
                //
                // Ось колеса — Z, середина колеса — Z=0.
                // Способ размещения цилиндров перенесён
                // из предоставленного рабочего макроса.
                // =====================================================

                double flangeWidth =
                    (width - grooveWidth) / 2.0;

                double flangeZ =
                    (width + grooveWidth) / 4.0;

                double pocketDepth =
                    (width - webWidth) / 2.0;

                double pocketToolWidth =
                    pocketDepth + extra;

                double pocketZ =
                    (width + webWidth) / 4.0 + extra / 2.0;

                double protectorWidth =
                    pocketToolWidth + 2.0 * extra;

                double boreToolWidth =
                    hubWidth + 2.0 * extra;

                step = "Сердцевина и реборды";

                Cylinder core = AddCylinder(
                    doc, FirstName,
                    dTrack, width, 0.0);

                Cylinder leftFlange = AddCylinder(
                    doc, "WH 02 Левая реборда",
                    dOuter, flangeWidth, -flangeZ);

                Cylinder rightFlange = AddCylinder(
                    doc, "WH 03 Правая реборда",
                    dOuter, flangeWidth, flangeZ);

                Operation body = Apply(
                    doc, "WH 04 Обод с левой ребордой",
                    BooleanOperation.FunctionType.Unite,
                    core, leftFlange);

                body = Apply(
                    doc, "WH 05 Обод с двумя ребордами",
                    BooleanOperation.FunctionType.Unite,
                    body, rightFlange);

                step = "Ступица";

                Cylinder hub = AddCylinder(
                    doc, "WH 06 Ступица",
                    dHub, hubWidth, 0.0);

                body = Apply(
                    doc, "WH 07 Объединение со ступицей",
                    BooleanOperation.FunctionType.Unite,
                    body, hub);

                step = "Левый кольцевой инструмент";

                // Кольцевой инструмент удаляет материал между
                // диаметрами DHub и DPocket.
                // Центральная ступица при этом сохраняется.

                Operation leftPocket = AddRingTool(
                    doc,
                    "WH 08 Левая торцевая выборка",
                    dPocket,
                    dHub,
                    pocketToolWidth,
                    protectorWidth,
                    -pocketZ);

                step = "Правый кольцевой инструмент";

                Operation rightPocket = AddRingTool(
                    doc,
                    "WH 09 Правая торцевая выборка",
                    dPocket,
                    dHub,
                    pocketToolWidth,
                    protectorWidth,
                    pocketZ);

                step = "Вычитание левой торцевой выборки";

                body = Apply(
                    doc, "WH 10 Левая выборка",
                    BooleanOperation.FunctionType.Subtract,
                    body, leftPocket);

                step = "Вычитание правой торцевой выборки";

                body = Apply(
                    doc, "WH 11 Правая выборка",
                    BooleanOperation.FunctionType.Subtract,
                    body, rightPocket);

                step = "Сквозное осевое отверстие";

                Cylinder bore = AddCylinder(
                    doc, "WH 12 Инструмент осевого отверстия",
                    dBore, boreToolWidth, 0.0);

                body = Apply(
                    doc, FinalName,
                    BooleanOperation.FunctionType.Subtract,
                    body, bore);

                step = "Применение изменений";

                // Результат обязательно сохраняем для диагностики.
                var endResult = doc.EndChanges();
                editing = false;
                endResultText = Convert.ToString(endResult);

                // После завершения изменений не используем старую
                // ссылку на итоговую операцию.
                body = null;

                // Дополнительный Regenerate здесь намеренно исключён.
                step = "Проверка итоговой операции";

                Document currentDoc = Application.ActiveDocument;

                if (currentDoc == null)
                {
                    throw new InvalidOperationException(
                        "После EndChanges отсутствует активный документ.");
                }

                var found = currentDoc.GetObjectByName(FinalName);

                if (found == null)
                {
                    throw new InvalidOperationException(
                        "Итоговая операция WH 13 не найдена " +
                        "после применения изменений.");
                }

                Operation finalBody = found as Operation;

                if (finalBody == null)
                {
                    throw new InvalidOperationException(
                        "WH 13 найдена, но не является операцией.");
                }

                step = "Проверка итогового тела";

                if (finalBody.Body == null ||
                    finalBody.Geometry == null)
                {
                    throw new InvalidOperationException(
                        "WH 13 найдена, но итоговое тело не сформировано. " +
                        "Проверьте диагностику операций документа.");
                }
            }
            catch (Exception ex)
            {
                string cancelError = "";

                if (editing)
                {
                    try
                    {
                        doc.CancelChanges();
                    }
                    catch (Exception cancelException)
                    {
                        cancelError =
                            " Ошибка отмены изменений: " +
                            cancelException.GetBaseException().Message;
                    }
                }

                // Повторно получаем активный документ для диагностики.
                Document diagnosticDoc =
                    Application.ActiveDocument;

                if (diagnosticDoc == null)
                    diagnosticDoc = doc;

                diagnosticDoc.Diagnostics.Add(
                    new DiagnosticsMessage(
                        DiagnosticsMessageType.Error,
                        "Колесо — " + step + ": " +
                        ex.GetBaseException().Message +
                        " Результат EndChanges: " +
                        endResultText + "." +
                        cancelError));
            }
        }

        // Создаёт основной параметр, если его ещё нет.
        // Существующее числовое значение не перезаписывает.
        private static void Input(
            Document doc,
            string name,
            double initialValue,
            string comment)
        {
            string fullName = Prefix + name;
            Variable variable = doc.FindVariable(fullName);

            if (variable == null)
            {
                variable = new Variable(
                    doc, fullName, initialValue);
            }

            if (!variable.IsReal)
            {
                throw new InvalidOperationException(
                    "Не числовая переменная: " + fullName);
            }

            variable.Comment = comment;
        }

        // Получает положительное конечное числовое значение.
        private static double Value(
            Document doc,
            string name)
        {
            string fullName = Prefix + name;
            Variable variable = doc.FindVariable(fullName);

            if (variable == null)
            {
                throw new InvalidOperationException(
                    "Не найдена переменная: " + fullName);
            }

            if (!variable.IsReal)
            {
                throw new InvalidOperationException(
                    "Не числовая переменная: " + fullName);
            }

            double value = variable.RealValue;

            if (Double.IsNaN(value) ||
                Double.IsInfinity(value) ||
                value <= 0.0)
            {
                throw new InvalidOperationException(
                    fullName +
                    " должна быть положительным конечным числом.");
            }

            return value;
        }

        // Создаёт цилиндр и перемещает его вдоль оси Z.
        // Все размеры задаются числовыми Parameter.
        private static Cylinder AddCylinder(
            Document doc,
            string name,
            double diameter,
            double height,
            double z)
        {
            if (diameter <= 0.0 || height <= 0.0)
            {
                throw new InvalidOperationException(
                    "Недопустимые размеры цилиндра: " + name);
            }

            Cylinder item = new Cylinder(doc);
            item.Name = name;
            item.Symmetry = false;
            item.Diameter = new Parameter(diameter);
            item.Height = new Parameter(height);

            TransformationGroupContainer transforms =
                item.Transformations;

            transforms.DeleteAllBaseTransfGroups();

            TransformationGroupBase group =
                transforms.AddBaseTransfGroup();

            if (z != 0.0)
            {
                group.AddMoveTransf(
                    TransformationCoordinate.Z,
                    new Parameter(z));
            }

            return item;
        }

        // Создаёт полый цилиндр для торцевой выборки.
        // Внутренний цилиндр длиннее наружного,
        // чтобы гарантированно прорезать инструмент насквозь.
        private static Operation AddRingTool(
            Document doc,
            string name,
            double outerDiameter,
            double innerDiameter,
            double outerHeight,
            double innerHeight,
            double z)
        {
            Cylinder outer = AddCylinder(
                doc,
                name + " - наружный цилиндр",
                outerDiameter,
                outerHeight,
                z);

            Cylinder inner = AddCylinder(
                doc,
                name + " - защита ступицы",
                innerDiameter,
                innerHeight,
                z);

            return Apply(
                doc,
                name + " - кольцевой инструмент",
                BooleanOperation.FunctionType.Subtract,
                outer,
                inner);
        }

        // Булевы операции оформлены по рабочему образцу пользователя.
        private static Operation Apply(
            Document doc,
            string name,
            BooleanOperation.FunctionType function,
            Operation first,
            Operation second)
        {
            BooleanOperation result =
                new BooleanOperation(doc);

            result.Name = name;
            result.Function = function;

            result.FirstOperands.Add(
                new BooleanOperation.OperandsArray.Operand(
                    first, false));

            result.SecondOperands.Add(
                new BooleanOperation.OperandsArray.Operand(
                    second, false));

            return result;
        }
    }
}